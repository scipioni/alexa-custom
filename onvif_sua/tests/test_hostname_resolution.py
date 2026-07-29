"""Cameras configured by ONVIF `hostname` instead of a static `ip`: config parsing,
the subnet-sweep resolver (including the refuse-to-guess ambiguity rule), worker
migration on an IP change, and the rename/remove paths that must locate a hostname
entry by hostname rather than by the runtime IP."""
import asyncio
import json

import pytest

from onvif_sua import config, scan, state, worker
from onvif_sua.web import routes


# ── harness ──────────────────────────────────────────────────────────────────────
class _FakeReq:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


def _run(coro):
    return asyncio.run(coro)


def _body(resp):
    return json.loads(resp.body)


def _dev(ip, hostname, name=None, port=80):
    """A synthetic `_probe_ip` result: an online ONVIF device reporting `hostname`."""
    return {"ip": ip, "name": name or hostname, "hostname": hostname,
            "user": "admin", "pass": "pw", "port": port}


@pytest.fixture
def hostname_env(restore_globals, monkeypatch):
    """Clean hostname cache + resolver log-dedupe state, a real (non-placeholder)
    password so the sweep guard does not short-circuit, and no settings.yaml writes."""
    with state._lock:
        state._hostname_ips.clear()
    scan._reset_resolve_log_state()
    config._settings_doc.clear()
    monkeypatch.setattr(config, "_save_settings_yaml", lambda: None)
    monkeypatch.setattr(config, "_password_placeholder_flags",
                        lambda: {"cameras": False, "scan": False})
    monkeypatch.setattr(config, "_COMMON_CRED",
                        {"user": "admin", "pass": "realpw", "port": 80})
    config._cfg["scan_subnet"] = "10.9.0.0/29"
    yield
    with state._lock:
        state._hostname_ips.clear()
    scan._reset_resolve_log_state()
    config._settings_doc.clear()


@pytest.fixture
def sweep(monkeypatch):
    """Install a synthetic subnet sweep. `sweep.devices` is the list returned to the
    resolver; assignment order is the probe-completion order the resolver sees."""

    class _Sweep:
        devices: list = []

        async def __call__(self, hosts):
            return list(self.devices)

    s = _Sweep()
    monkeypatch.setattr(scan, "_sweep_probe_all", s)
    return s


# ── 6.1 config parsing ───────────────────────────────────────────────────────────
def _load(entries):
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": entries}
    return config._load_static_cameras()[1]


def test_parse_hostname_only_accepted(hostname_env):
    cams = _load([{"hostname": "STANZA_11", "name": "soggiorno"}])
    assert cams == [{"hostname": "STANZA_11", "name": "soggiorno"}]
    assert "ip" not in cams[0]   # a hostname is never treated as an address


def test_parse_ip_only_unchanged(hostname_env):
    cams = _load([{"ip": "10.0.0.1", "name": "cucina"}])
    assert cams == [{"ip": "10.0.0.1", "name": "cucina"}]


def test_parse_hostname_equal_to_name_accepted(hostname_env, capsys):
    cams = _load([{"hostname": "soggiorno", "name": "soggiorno"}])
    assert cams == [{"hostname": "soggiorno", "name": "soggiorno"}]
    assert "duplicat" not in capsys.readouterr().out


def test_parse_rejects_neither_ip_nor_hostname(hostname_env, capsys):
    cams = _load([{"name": "orfana"}, {"ip": "10.0.0.1", "name": "cucina"}])
    assert cams == [{"ip": "10.0.0.1", "name": "cucina"}]
    assert "manca sia 'ip' che 'hostname'" in capsys.readouterr().out


def test_parse_rejects_both_ip_and_hostname(hostname_env, capsys):
    cams = _load([{"ip": "10.0.0.1", "hostname": "STANZA_11", "name": "ambigua"}])
    assert cams == []
    assert "sia 'ip' che 'hostname'" in capsys.readouterr().out


def test_parse_duplicate_hostname_drops_both(hostname_env, capsys):
    cams = _load([
        {"hostname": "STANZA_11", "name": "soggiorno"},
        {"hostname": "stanza_11", "name": "bagno"},      # same hostname, different case
        {"ip": "10.0.0.3", "name": "cucina"},
    ])
    assert cams == [{"ip": "10.0.0.3", "name": "cucina"}]
    assert "hostname duplicato" in capsys.readouterr().out


def test_parse_duplicate_name_across_mixed_entries_drops_both(hostname_env, capsys):
    cams = _load([
        {"hostname": "STANZA_11", "name": "soggiorno"},
        {"ip": "10.0.0.2", "name": "soggiorno"},
    ])
    assert cams == []
    assert "name duplicato" in capsys.readouterr().out


def test_parse_duplicate_ip_still_drops_both_with_hostname_entries_present(hostname_env):
    cams = _load([
        {"hostname": "STANZA_11", "name": "soggiorno"},
        {"ip": "10.0.0.2", "name": "cucina"},
        {"ip": "10.0.0.2", "name": "bagno"},
    ])
    assert cams == [{"hostname": "STANZA_11", "name": "soggiorno"}]


def test_save_never_persists_a_resolved_ip(hostname_env, monkeypatch, tmp_path):
    """A save while a hostname camera is resolved leaves `hostname` in the file and
    writes no `ip` for it."""
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": [
        {"hostname": "STANZA_11", "name": "soggiorno"},
    ]}
    state._set_resolved_ip("STANZA_11", "10.9.0.4")
    target = tmp_path / "settings.yaml"
    monkeypatch.setattr(config, "SETTINGS_FILE", str(target))
    monkeypatch.undo()   # drop the _save_settings_yaml stub for this test
    monkeypatch.setattr(config, "SETTINGS_FILE", str(target))
    config._save_settings_yaml()
    text = target.read_text()
    assert "hostname: STANZA_11" in text
    assert "10.9.0.4" not in text


# ── 6.2 resolver: hostname → IP over one sweep ────────────────────────────────────
def test_resolver_matches_case_insensitively_and_trimmed(hostname_env, sweep):
    sweep.devices = [_dev("10.9.0.2", " Stanza_11 "), _dev("10.9.0.3", "BAGNO")]
    got = _run(scan._resolve_hostnames(["STANZA_11", "  bagno"]))
    assert got == {"stanza_11": "10.9.0.2", "bagno": "10.9.0.3"}


def test_resolver_one_sweep_for_all_hostnames(hostname_env, sweep, monkeypatch):
    calls = []
    inner = sweep.__call__

    async def counting(hosts):
        calls.append(len(hosts))
        return await inner(hosts)

    monkeypatch.setattr(scan, "_sweep_probe_all", counting)
    sweep.devices = [_dev("10.9.0.2", "a"), _dev("10.9.0.3", "b"), _dev("10.9.0.4", "c")]
    got = _run(scan._resolve_hostnames(["a", "b", "c"]))
    assert got == {"a": "10.9.0.2", "b": "10.9.0.3", "c": "10.9.0.4"}
    assert calls == [6]   # ONE sweep over the /29's six hosts, not one per camera


def test_resolver_no_match_leaves_hostname_out(hostname_env, sweep):
    sweep.devices = [_dev("10.9.0.2", "qualcosaltro")]
    assert _run(scan._resolve_hostnames(["stanza_11"])) == {}


def test_resolver_ignores_devices_without_a_hostname(hostname_env, sweep):
    sweep.devices = [_dev("10.9.0.2", "")]
    assert _run(scan._resolve_hostnames(["stanza_11"])) == {}


def test_resolver_logs_unmatched_online_devices_once(hostname_env, sweep, capsys):
    sweep.devices = [_dev("10.9.0.2", "stanza_11"), _dev("10.9.0.3", "sconosciuta")]
    _run(scan._resolve_hostnames(["stanza_11"]))
    assert "senza voce in cameras.list" in capsys.readouterr().out
    _run(scan._resolve_hostnames(["stanza_11"]))            # unchanged set → silent
    assert "senza voce in cameras.list" not in capsys.readouterr().out
    sweep.devices.append(_dev("10.9.0.4", "altra"))          # set changed → logs again
    _run(scan._resolve_hostnames(["stanza_11"]))
    assert "senza voce in cameras.list" in capsys.readouterr().out


def test_resolver_skips_sweep_while_password_is_placeholder(hostname_env, sweep, monkeypatch):
    monkeypatch.setattr(config, "_password_placeholder_flags",
                        lambda: {"cameras": True, "scan": True})
    sweep.devices = [_dev("10.9.0.2", "stanza_11")]
    assert _run(scan._resolve_hostnames(["stanza_11"])) == {}


# ── 6.2b ambiguity: refuse rather than guess ──────────────────────────────────────
def test_ambiguous_hostname_resolves_to_neither(hostname_env, sweep, capsys):
    sweep.devices = [_dev("10.9.0.2", "stanza_11"), _dev("10.9.0.3", "stanza_11")]
    assert _run(scan._resolve_hostnames(["stanza_11"])) == {}
    out = capsys.readouterr().out
    assert "AMBIGUO" in out and "10.9.0.2" in out and "10.9.0.3" in out


def test_ambiguity_diagnostic_not_repeated_until_the_set_changes(hostname_env, sweep, capsys):
    sweep.devices = [_dev("10.9.0.2", "stanza_11"), _dev("10.9.0.3", "stanza_11")]
    _run(scan._resolve_hostnames(["stanza_11"]))
    assert "AMBIGUO" in capsys.readouterr().out
    _run(scan._resolve_hostnames(["stanza_11"]))                 # same candidates
    assert "AMBIGUO" not in capsys.readouterr().out
    sweep.devices.append(_dev("10.9.0.4", "stanza_11"))          # candidate set changed
    _run(scan._resolve_hostnames(["stanza_11"]))
    assert "AMBIGUO" in capsys.readouterr().out


def test_ambiguity_clears_on_the_next_sweep(hostname_env, sweep):
    sweep.devices = [_dev("10.9.0.2", "stanza_11"), _dev("10.9.0.3", "stanza_11")]
    assert _run(scan._resolve_hostnames(["stanza_11"])) == {}
    sweep.devices = [_dev("10.9.0.2", "stanza_11"), _dev("10.9.0.3", "stanza_12")]
    assert _run(scan._resolve_hostnames(["stanza_11"])) == {"stanza_11": "10.9.0.2"}


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_two_hostnames_on_one_ip_lowest_config_index_wins(hostname_env, sweep, order):
    """A device answering for two configured hostnames must not let probe-completion
    order decide the winner — the entry earlier in `cameras.list` keeps the IP."""
    devs = [_dev("10.9.0.2", "primo"), _dev("10.9.0.2", "secondo")]
    sweep.devices = [devs[order[0]], devs[order[1]]]
    got = _run(scan._resolve_hostnames(["primo", "secondo"]))
    assert got == {"primo": "10.9.0.2"}
    sweep.devices = [devs[order[0]], devs[order[1]]]
    got = _run(scan._resolve_hostnames(["secondo", "primo"]))   # config order flipped
    assert got == {"secondo": "10.9.0.2"}


# ── 6.3 / 6.2b(b,c) worker lifecycle on the resolution tick ───────────────────────
@pytest.fixture
def tick(hostname_env, monkeypatch):
    """Drive worker._hostname_resolve_tick with a stubbed resolver and recorded
    teardown/spawn calls. `tick.resolved` is what the resolver returns."""

    class _Tick:
        def __init__(self):
            self.resolved = {}
            self.spawned = []
            self.torn = []

        async def _resolve(self, wanted):
            self.wanted = list(wanted)
            return dict(self.resolved)

        async def _teardown(self, ip):
            self.torn.append(ip)
            state._worker_tasks.pop(ip, None)
            return True

        def _spawn(self, info):
            self.spawned.append(info)
            state._worker_tasks[info["ip"]] = object()

        def run(self):
            _run(worker._hostname_resolve_tick())

    t = _Tick()
    monkeypatch.setattr(scan, "_resolve_hostnames", t._resolve)
    monkeypatch.setattr(worker, "_teardown_camera", t._teardown)
    monkeypatch.setattr(worker, "_spawn_worker", t._spawn)
    yield t
    state._worker_tasks.clear()


def test_tick_spawns_worker_once_hostname_resolves(tick):
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    assert [(i["ip"], i["name"], i["hostname"]) for i in tick.spawned] == \
        [("10.9.0.2", "soggiorno", "STANZA_11")]
    assert state._resolved_ip("STANZA_11") == "10.9.0.2"


def test_tick_migrates_worker_on_ip_change(tick):
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    tick.resolved = {"stanza_11": "10.9.0.7"}
    tick.run()
    assert tick.torn == ["10.9.0.2"]
    assert [(i["ip"], i["name"]) for i in tick.spawned] == \
        [("10.9.0.2", "soggiorno"), ("10.9.0.7", "soggiorno")]
    assert state._resolved_ip("STANZA_11") == "10.9.0.7"


def test_tick_unchanged_ip_is_a_noop(tick):
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    tick.run()
    assert tick.torn == [] and len(tick.spawned) == 1


def test_tick_failed_resolution_keeps_running_worker(tick):
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    tick.resolved = {}          # scan blip / device silent
    tick.run()
    assert tick.torn == [] and len(tick.spawned) == 1
    assert state._resolved_ip("STANZA_11") == "10.9.0.2"


def test_tick_never_resolved_hostname_spawns_nothing_and_is_retried(tick):
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {}
    tick.run()
    tick.run()
    assert tick.spawned == [] and state._resolved_ip("STANZA_11") is None
    tick.resolved = {"stanza_11": "10.9.0.5"}
    tick.run()
    assert [i["ip"] for i in tick.spawned] == ["10.9.0.5"]


def test_tick_ambiguity_does_not_disturb_a_running_worker(tick):
    """An ambiguous hostname is absent from the resolver's map — same as a failure."""
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    tick.resolved = {}          # ambiguous: two devices report it
    tick.run()
    assert tick.torn == [] and len(tick.spawned) == 1
    assert state._resolved_ip("STANZA_11") == "10.9.0.2"


def test_tick_ambiguity_with_running_ip_not_among_candidates_still_no_migration(tick):
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    # The two ambiguous candidates are .8 and .9 — neither is the running .2. The
    # resolver still reports nothing, and nothing may move.
    tick.resolved = {}
    tick.run()
    assert tick.torn == [] and [i["ip"] for i in tick.spawned] == ["10.9.0.2"]
    assert state._resolved_ip("STANZA_11") == "10.9.0.2"


def test_tick_ignores_static_ip_cameras(tick):
    config._static_cameras = [{"ip": "10.0.0.1", "name": "cucina"}]
    tick.resolved = {"cucina": "10.9.0.2"}
    tick.run()
    assert tick.spawned == [] and tick.torn == []


def test_tick_refuses_an_ip_pinned_by_a_static_entry(tick, capsys):
    config._static_cameras = [
        {"ip": "10.9.0.2", "name": "cucina"},
        {"hostname": "STANZA_11", "name": "soggiorno"},
    ]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    assert tick.spawned == []
    assert "ip statico" in capsys.readouterr().out


def test_tick_does_not_touch_the_manual_scan_flag(tick):
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    before = scan._scan_active
    tick.run()
    assert scan._scan_active is before is False
    assert not scan._scan_cancel.is_set()


def test_tick_skipped_while_password_is_placeholder(tick, monkeypatch):
    monkeypatch.setattr(config, "_COMMON_CRED",
                        {"user": "admin", "pass": config.DEFAULT_PASSWORD_SENTINEL, "port": 80})
    config._static_cameras = [{"hostname": "STANZA_11", "name": "soggiorno"}]
    tick.resolved = {"stanza_11": "10.9.0.2"}
    tick.run()
    assert tick.spawned == []


# ── 6.6 config helpers must match a hostname entry, not the string "None" ─────────
@pytest.fixture
def one_hostname_cam(hostname_env):
    """One hostname entry (resolved to 10.9.0.2) plus one static entry."""
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": [
        {"hostname": "STANZA_11", "name": "sala_pranzo"},
        {"ip": "10.0.0.9", "name": "cucina"},
    ]}
    config._static_cameras = [
        {"hostname": "STANZA_11", "name": "sala_pranzo"},
        {"ip": "10.0.0.9", "name": "cucina"},
    ]
    state._set_resolved_ip("STANZA_11", "10.9.0.2")
    return config._settings_doc["cameras"]["list"]


def test_add_camera_with_hostname_updates_in_place(one_hostname_cam):
    ok, msg = config._config_add_camera("10.9.0.2", "salotto", 80, hostname="STANZA_11")
    assert ok and msg == "aggiornata"
    assert len(one_hostname_cam) == 2                       # no appended duplicate
    assert one_hostname_cam[0] == {"hostname": "STANZA_11", "name": "salotto"}
    assert "ip" not in one_hostname_cam[0]


def test_add_camera_rewrites_hostname_when_asked(one_hostname_cam):
    ok, _ = config._config_add_camera("10.9.0.2", "salotto", 80,
                                      hostname="STANZA_11", set_hostname="salotto")
    assert ok
    assert one_hostname_cam[0] == {"hostname": "salotto", "name": "salotto"}


def test_add_camera_with_unknown_hostname_never_appends(one_hostname_cam):
    ok, msg = config._config_add_camera("10.9.0.2", "salotto", 80, hostname="mai-vista")
    assert ok is False and "Nessuna voce" in msg
    assert len(one_hostname_cam) == 2


def test_add_camera_static_entry_gains_no_hostname_key(one_hostname_cam):
    ok, _ = config._config_add_camera("10.0.0.9", "cucinetta", 80)
    assert ok
    assert one_hostname_cam[1] == {"ip": "10.0.0.9", "name": "cucinetta"}


def test_remove_camera_by_hostname(one_hostname_cam):
    assert config._config_remove_camera("10.9.0.2", hostname="STANZA_11") is True
    assert config._settings_doc["cameras"]["list"] == [{"ip": "10.0.0.9", "name": "cucina"}]


def test_remove_camera_by_ip_leaves_a_hostname_entry_alone(one_hostname_cam):
    assert config._config_remove_camera("10.9.0.2") is False
    assert len(config._settings_doc["cameras"]["list"]) == 2


def test_remove_static_camera_unchanged(one_hostname_cam):
    assert config._config_remove_camera("10.0.0.9") is True
    assert config._settings_doc["cameras"]["list"] == [
        {"hostname": "STANZA_11", "name": "sala_pranzo"}]


def test_name_conflict_does_not_report_a_hostname_entry_against_itself(one_hostname_cam):
    assert config._config_name_conflict("10.9.0.2", "sala_pranzo", "STANZA_11") is None
    # ...and without the hostname it wrongly would (the "None" comparison):
    assert config._config_name_conflict("10.9.0.2", "sala_pranzo") == "STANZA_11"


def test_voice_collision_allows_renaming_a_hostname_camera_to_its_own_variant(one_hostname_cam):
    # 'sala_pranzo' → 'sala pranzo' normalises to the same voice name: not a collision
    assert config._name_voice_collision("10.9.0.2", "sala pranzo", "STANZA_11") is None
    assert config._name_voice_collision("10.9.0.2", "SALA-PRANZO", "STANZA_11") is None


def test_genuine_conflict_against_a_hostname_entry_names_the_hostname(one_hostname_cam):
    label = config._config_name_conflict("10.0.0.9", "sala_pranzo", None)
    assert label == "STANZA_11" and label != "None"
    coll = config._name_voice_collision("10.0.0.9", "sala pranzo", None)
    assert coll == "STANZA_11"


def test_static_helpers_behave_as_before(one_hostname_cam):
    assert config._config_name_conflict("10.0.0.1", "cucina") == "10.0.0.9"
    assert config._config_name_conflict("10.0.0.9", "cucina") is None
    assert config._name_voice_collision("10.0.0.1", "cucina") == "10.0.0.9"
    assert config._name_voice_collision("10.0.0.9", "cucina") is None


def test_hostname_conflict_detects_a_hijacking_rename(one_hostname_cam):
    assert config._config_hostname_conflict("STANZA-11") is None      # '-' ≠ '_'
    assert config._config_hostname_conflict("stanza_11") == "STANZA_11"
    # ...but the camera's OWN hostname is always allowed
    assert config._config_hostname_conflict("stanza_11", "STANZA_11") is None


# ── 6.4 / 6.5 rename ─────────────────────────────────────────────────────────────
@pytest.fixture
def fake_onvif(monkeypatch):
    """Fake ONVIFCamera: records SetHostname calls and replays a configurable
    GetHostname answer (`fake.reported`, or None to make the read fail)."""
    import onvif

    class _Fake:
        set_calls: list = []
        reported = None        # None → mirror what was set
        read_fails = False

        class _Hostname:
            def __init__(self, name):
                self.Name = name

        def _dev(fake):
            class _Dev:
                async def SetHostname(self, arg):
                    fake.set_calls.append(arg["Name"])

                async def GetHostname(self):
                    if fake.read_fails:
                        raise RuntimeError("read failed")
                    name = fake.reported if fake.reported is not None else (
                        fake.set_calls[-1] if fake.set_calls else "")
                    return fake._Hostname(name)
            return _Dev()

    fake = _Fake()
    fake.set_calls = []

    class _Cam:
        def __init__(self, *a, **k):
            pass

        async def update_xaddrs(self):
            return None

        async def create_devicemgmt_service(self):
            return fake._dev()

        async def close(self):
            return None

    monkeypatch.setattr(onvif, "ONVIFCamera", _Cam)

    async def _noclose(c):
        return None

    monkeypatch.setattr(routes, "_safe_close", _noclose)
    return fake


def _live_cam(ip, name):
    with state._lock:
        state._cameras[ip] = worker._new_cam(ip, name, "admin", "realpw", 80)
    return state._cameras[ip]


def test_rename_hostname_camera_rewrites_hostname_and_name(one_hostname_cam, fake_onvif):
    _live_cam("10.9.0.2", "sala_pranzo")
    resp = _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "salotto"})))
    assert resp.status_code == 200 and _body(resp)["saved"] is True
    assert len(one_hostname_cam) == 2                       # exactly one entry per camera
    assert one_hostname_cam[0] == {"hostname": "salotto", "name": "salotto"}
    assert "ip" not in one_hostname_cam[0]
    assert fake_onvif.set_calls == ["salotto"]


def test_rename_persists_the_hostname_the_device_reports(one_hostname_cam, fake_onvif):
    _live_cam("10.9.0.2", "sala_pranzo")
    fake_onvif.reported = "salott"                          # firmware truncated it
    resp = _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "salotto"})))
    assert resp.status_code == 200
    assert one_hostname_cam[0] == {"hostname": "salott", "name": "salotto"}
    assert _body(resp)["verified"] is False


def test_rename_with_failed_verification_read_persists_the_request_and_warns(
        one_hostname_cam, fake_onvif, capsys):
    _live_cam("10.9.0.2", "sala_pranzo")
    fake_onvif.read_fails = True
    resp = _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "salotto"})))
    assert resp.status_code == 200
    assert one_hostname_cam[0] == {"hostname": "salotto", "name": "salotto"}
    out = capsys.readouterr().out
    assert "rilettura hostname fallita" in out and "STANZA_11" in out


def test_rename_hijacking_another_entrys_hostname_is_rejected(one_hostname_cam, fake_onvif):
    _live_cam("10.0.0.9", "cucina")
    config._settings_doc["cameras"]["list"][0]["hostname"] = "salotto"
    resp = _run(routes.api_rename_camera("10.0.0.9", _FakeReq({"name": "salotto"})))
    assert resp.status_code == 409
    assert "hostname configurato" in _body(resp)["detail"]
    assert fake_onvif.set_calls == []                       # device never touched
    assert config._settings_doc["cameras"]["list"][1]["name"] == "cucina"


def test_rename_to_own_hostname_proceeds(one_hostname_cam, fake_onvif):
    """The hijack check must fire only against ANOTHER entry's hostname — a camera
    renamed to the hostname it already answers to is a legitimate no-op rename."""
    one_hostname_cam[0]["hostname"] = "STANZA-11"
    config._static_cameras[0]["hostname"] = "STANZA-11"
    state._drop_resolved_hostname("STANZA_11")
    state._set_resolved_ip("STANZA-11", "10.9.0.2")
    _live_cam("10.9.0.2", "sala_pranzo")
    resp = _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "STANZA-11"})))
    assert resp.status_code == 200
    assert fake_onvif.set_calls == ["STANZA-11"]
    assert one_hostname_cam[0] == {"hostname": "STANZA-11", "name": "STANZA-11"}


def test_rename_rekeys_the_cache_and_spawns_no_worker(one_hostname_cam, fake_onvif):
    _live_cam("10.9.0.2", "sala_pranzo")
    _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "salotto"})))
    assert state._resolved_ip("salotto") == "10.9.0.2"
    assert state._resolved_ip("STANZA_11") is None
    assert state._worker_tasks == {}                        # no teardown/respawn


def test_rename_failure_to_save_reports_failure_and_logs_the_device_hostname(
        one_hostname_cam, fake_onvif, monkeypatch, capsys):
    _live_cam("10.9.0.2", "sala_pranzo")
    monkeypatch.setattr(routes, "_config_add_camera",
                        lambda *a, **k: (False, "disco pieno"))
    resp = _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "salotto"})))
    assert resp.status_code == 500 and _body(resp)["saved"] is False
    out = capsys.readouterr().out
    assert "correggi a mano" in out and "salotto" in out


def test_rename_static_camera_gains_no_hostname_key(one_hostname_cam, fake_onvif):
    _live_cam("10.0.0.9", "cucina")
    resp = _run(routes.api_rename_camera("10.0.0.9", _FakeReq({"name": "cucinetta"})))
    assert resp.status_code == 200
    assert one_hostname_cam[1] == {"ip": "10.0.0.9", "name": "cucinetta"}
    assert "hostname" not in one_hostname_cam[1]


def test_rename_of_unresolved_hostname_camera_is_not_found(one_hostname_cam, fake_onvif):
    state._drop_resolved_hostname("STANZA_11")              # never resolved
    resp = _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "salotto"})))
    assert resp.status_code == 404
    assert fake_onvif.set_calls == []
    assert one_hostname_cam[0] == {"hostname": "STANZA_11", "name": "sala_pranzo"}


def test_first_sweep_after_a_rename_spawns_no_second_worker(
        one_hostname_cam, fake_onvif, sweep, monkeypatch):
    """6.5: the rewritten hostname matches the device's new hostname on the next tick,
    the resolved IP equals the running worker's IP, and nothing is spawned again."""
    _live_cam("10.9.0.2", "sala_pranzo")
    state._worker_tasks["10.9.0.2"] = object()
    spawned, torn = [], []
    monkeypatch.setattr(worker, "_spawn_worker", lambda info: spawned.append(info))

    async def _teardown(ip):
        torn.append(ip)
        return True

    monkeypatch.setattr(worker, "_teardown_camera", _teardown)
    try:
        _run(routes.api_rename_camera("10.9.0.2", _FakeReq({"name": "salotto"})))
        sweep.devices = [_dev("10.9.0.2", "salotto")]
        _run(worker._hostname_resolve_tick())
        assert spawned == [] and torn == []
        assert state._resolved_ip("salotto") == "10.9.0.2"
    finally:
        state._worker_tasks.clear()


# ── 6.7 removal durability ────────────────────────────────────────────────────────
def test_removed_hostname_camera_does_not_come_back(
        one_hostname_cam, sweep, monkeypatch):
    _live_cam("10.9.0.2", "sala_pranzo")
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    spawned = []
    monkeypatch.setattr(worker, "_spawn_worker", lambda info: spawned.append(info))

    resp = _run(routes.api_remove_camera("10.9.0.2", _FakeReq({})))
    assert _body(resp)["removed_config"] is True
    assert config._settings_doc["cameras"]["list"] == [{"ip": "10.0.0.9", "name": "cucina"}]
    assert state._resolved_ip("STANZA_11") is None
    assert not any(c.get("hostname") == "STANZA_11" for c in config._static_cameras)

    # The device is still online and still reports its hostname — it must NOT respawn.
    sweep.devices = [_dev("10.9.0.2", "STANZA_11")]
    _run(worker._hostname_resolve_tick())
    assert spawned == []


def test_remove_static_camera_unchanged_by_the_hostname_path(
        one_hostname_cam, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    resp = _run(routes.api_remove_camera("10.0.0.9", _FakeReq({})))
    assert _body(resp)["removed_config"] is True
    assert config._settings_doc["cameras"]["list"] == [
        {"hostname": "STANZA_11", "name": "sala_pranzo"}]
    assert state._resolved_ip("STANZA_11") == "10.9.0.2"   # untouched


# ── saving a discovered camera persists a `hostname:` entry ───────────────────────
def _discovered(ip, name, onvif_hostname):
    """A camera row as the manual scan leaves it: not static, carrying the ONVIF
    hostname the probe read from the device."""
    with state._lock:
        cam = worker._new_cam(ip, name, "admin", "realpw", 80)
        cam["onvif_hostname"] = onvif_hostname
        cam["_static"] = False
        state._cameras[ip] = cam
    return cam


@pytest.fixture
def save_env(hostname_env, monkeypatch):
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": []}
    config._static_cameras = []
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    return config._settings_doc["cameras"]["list"]


def test_save_discovered_camera_writes_a_hostname_entry(save_env):
    _discovered("10.9.0.2", "provvisoria", "STANZA_11")
    resp = _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "cucina"})))
    assert resp.status_code == 200
    assert _body(resp)["hostname"] == "STANZA_11"
    assert save_env == [{"hostname": "STANZA_11", "name": "cucina"}]
    assert "ip" not in save_env[0]     # the resolved address is never persisted


def test_save_seeds_the_cache_and_the_static_list(save_env):
    _discovered("10.9.0.2", "provvisoria", "STANZA_11")
    _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "cucina"})))
    # reachable now, and visible to the resolution loop without a restart
    assert state._resolved_ip("STANZA_11") == "10.9.0.2"
    assert state._hostname_for_ip("10.9.0.2") == "STANZA_11"
    assert config._static_cameras == [{"hostname": "STANZA_11", "name": "cucina"}]


def test_saved_hostname_camera_survives_an_ip_change(save_env, tick):
    """The point of the whole thing: after a save, a new lease is followed by itself."""
    _discovered("10.9.0.2", "provvisoria", "STANZA_11")
    _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "cucina"})))
    state._worker_tasks["10.9.0.2"] = object()       # the scan's worker is running
    tick.resolved = {"stanza_11": "10.9.0.55"}       # DHCP moved it
    tick.run()
    assert tick.torn == ["10.9.0.2"]
    assert [(i["ip"], i["name"]) for i in tick.spawned] == [("10.9.0.55", "cucina")]
    assert state._resolved_ip("STANZA_11") == "10.9.0.55"


def test_save_falls_back_to_ip_when_the_device_reports_no_hostname(save_env, capsys):
    _discovered("10.9.0.2", "provvisoria", "")
    resp = _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "cucina"})))
    assert resp.status_code == 200 and _body(resp)["hostname"] == ""
    assert save_env == [{"ip": "10.9.0.2", "name": "cucina"}]
    assert "nessun hostname ONVIF disponibile" in capsys.readouterr().out
    assert state._resolved_hostnames() == {}


def test_save_refuses_a_hostname_already_used_by_another_entry(save_env):
    """Dahua ships every camera of a model with the same factory hostname (e.g. 'IPC').
    Two entries with one hostname are BOTH dropped at the next load, so refuse the save
    now rather than take two working cameras offline at the next restart."""
    save_env.append({"hostname": "IPC", "name": "soggiorno"})
    _discovered("10.9.0.3", "provvisoria", "IPC")
    resp = _run(routes.api_save_camera("10.9.0.3", _FakeReq({"name": "cucina"})))
    assert resp.status_code == 409
    detail = _body(resp)["detail"]
    assert "IPC" in detail and "soggiorno" in detail and "Rinomina" in detail
    assert save_env == [{"hostname": "IPC", "name": "soggiorno"}]   # nothing appended


def test_save_matches_the_existing_hostname_case_insensitively(save_env):
    save_env.append({"hostname": "ipc", "name": "soggiorno"})
    _discovered("10.9.0.3", "provvisoria", "IPC")
    resp = _run(routes.api_save_camera("10.9.0.3", _FakeReq({"name": "cucina"})))
    assert resp.status_code == 409


def test_save_leaves_an_existing_static_entry_static(save_env):
    """A save must not silently change how an already-configured camera is addressed."""
    save_env.append({"ip": "10.9.0.2", "name": "vecchio-nome"})
    config._static_cameras.append({"ip": "10.9.0.2", "name": "vecchio-nome"})
    _discovered("10.9.0.2", "vecchio-nome", "STANZA_11")
    resp = _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "cucina"})))
    assert resp.status_code == 200 and _body(resp)["hostname"] == ""
    assert save_env == [{"ip": "10.9.0.2", "name": "cucina"}]
    assert state._resolved_hostnames() == {}


def test_save_of_an_existing_hostname_entry_updates_it_in_place(save_env):
    save_env.append({"hostname": "STANZA_11", "name": "vecchio-nome"})
    config._static_cameras.append({"hostname": "STANZA_11", "name": "vecchio-nome"})
    state._set_resolved_ip("STANZA_11", "10.9.0.2")
    _discovered("10.9.0.2", "vecchio-nome", "STANZA_11")
    resp = _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "cucina"})))
    assert resp.status_code == 200
    assert save_env == [{"hostname": "STANZA_11", "name": "cucina"}]   # no second entry
    assert config._static_cameras == [{"hostname": "STANZA_11", "name": "cucina"}]


def test_save_still_rejects_a_reserved_name_before_writing_anything(save_env):
    _discovered("10.9.0.2", "provvisoria", "STANZA_11")
    resp = _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "camera-nuova"})))
    assert resp.status_code == 400
    assert save_env == [] and state._resolved_hostnames() == {}


# ── a scan must reconcile a configured hostname camera, never duplicate it ─────────
@pytest.fixture
def scan_env(hostname_env, monkeypatch):
    """Run the REAL _subnet_scan_once over a synthetic subnet with a stubbed probe."""

    class _S:
        def __init__(self):
            self.devices = {}
            self.discovered = []      # cameras spawned by the DISCOVERY path

        async def _probe(self, ip):
            return self.devices.get(ip)

        def run(self, automatic=True):
            _run(scan._subnet_scan_once(automatic=automatic))

    s = _S()
    monkeypatch.setattr(scan, "_probe_ip", s._probe)
    monkeypatch.setattr(scan, "_spawn_worker", lambda cam: s.discovered.append(cam))
    monkeypatch.setattr(config, "_password_placeholder_flags",
                        lambda: {"cameras": False, "scan": False})
    config._cfg["scan_subnet"] = "10.9.0.0/29"
    yield s
    with state._lock:
        state._cameras.clear()
        state._event_log.clear()
    state._worker_tasks.clear()


def test_scan_migrates_a_hostname_camera_that_moved_instead_of_duplicating_it(
        scan_env, monkeypatch):
    """The reported bug: the camera changed address, the automatic rescan found it at the
    new IP, and the dashboard ended up with two rows for one device."""
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": [
        {"hostname": "bagno1", "name": "bagno1"}]}
    config._static_cameras = [{"hostname": "bagno1", "name": "bagno1"}]
    state._set_resolved_ip("bagno1", "10.9.0.2")        # running here before the change
    state._worker_tasks["10.9.0.2"] = object()
    spawned, torn = [], []
    monkeypatch.setattr(worker, "_spawn_worker", lambda info: spawned.append(info))

    async def _teardown(ip):
        torn.append(ip)
        state._worker_tasks.pop(ip, None)
        return True

    monkeypatch.setattr(worker, "_teardown_camera", _teardown)
    scan_env.devices = {"10.9.0.5": _dev("10.9.0.5", "bagno1")}   # same device, new IP

    scan_env.run(automatic=True)

    assert torn == ["10.9.0.2"]                          # stale worker replaced
    assert [(i["ip"], i["name"]) for i in spawned] == [("10.9.0.5", "bagno1")]
    assert scan_env.discovered == []                     # NOT treated as a new discovery
    assert state._resolved_ip("bagno1") == "10.9.0.5"    # cache follows the address


def test_scan_does_not_respawn_a_hostname_camera_at_an_unchanged_ip(scan_env, monkeypatch):
    config._static_cameras = [{"hostname": "bagno1", "name": "bagno1"}]
    state._set_resolved_ip("bagno1", "10.9.0.2")
    state._worker_tasks["10.9.0.2"] = object()
    spawned, torn = [], []
    monkeypatch.setattr(worker, "_spawn_worker", lambda info: spawned.append(info))

    async def _teardown(ip):
        torn.append(ip)
        return True

    monkeypatch.setattr(worker, "_teardown_camera", _teardown)
    scan_env.devices = {"10.9.0.2": _dev("10.9.0.2", "bagno1")}
    scan_env.run(automatic=True)
    assert spawned == [] and torn == [] and scan_env.discovered == []


def test_scan_still_discovers_an_unconfigured_device(scan_env):
    config._static_cameras = [{"hostname": "bagno1", "name": "bagno1"}]
    state._set_resolved_ip("bagno1", "10.9.0.2")
    scan_env.devices = {
        "10.9.0.2": _dev("10.9.0.2", "bagno1"),      # configured → reconciled
        "10.9.0.6": _dev("10.9.0.6", "sconosciuta"),  # unconfigured → discovered
    }
    scan_env.run(automatic=True)
    assert [c["ip"] for c in scan_env.discovered] == ["10.9.0.6"]


def test_scan_leaves_an_ambiguous_hostname_alone(scan_env, monkeypatch):
    """Two devices reporting the configured hostname: no migration, and neither is
    adopted as a discovery under that camera's identity."""
    config._static_cameras = [{"hostname": "bagno1", "name": "bagno1"}]
    state._set_resolved_ip("bagno1", "10.9.0.2")
    state._worker_tasks["10.9.0.2"] = object()
    torn = []

    async def _teardown(ip):
        torn.append(ip)
        return True

    monkeypatch.setattr(worker, "_teardown_camera", _teardown)
    monkeypatch.setattr(worker, "_spawn_worker", lambda info: None)
    scan_env.devices = {"10.9.0.5": _dev("10.9.0.5", "bagno1"),
                        "10.9.0.6": _dev("10.9.0.6", "bagno1")}
    scan_env.run(automatic=True)
    assert torn == []
    assert state._resolved_ip("bagno1") == "10.9.0.2"     # unchanged
    assert scan_env.discovered == []                       # not adopted as discoveries


def test_scan_tears_down_a_stale_row_even_with_no_live_worker(scan_env, monkeypatch):
    """The camera's worker had already died on the old IP (address change mid-flight);
    the stale dashboard row must still go when the device reappears elsewhere."""
    config._static_cameras = [{"hostname": "bagno1", "name": "bagno1"}]
    state._set_resolved_ip("bagno1", "10.9.0.2")          # cached, but no _worker_tasks entry
    spawned, torn = [], []
    monkeypatch.setattr(worker, "_spawn_worker", lambda info: spawned.append(info))

    async def _teardown(ip):
        torn.append(ip)
        return True

    monkeypatch.setattr(worker, "_teardown_camera", _teardown)
    scan_env.devices = {"10.9.0.5": _dev("10.9.0.5", "bagno1")}
    scan_env.run(automatic=True)
    assert torn == ["10.9.0.2"]
    assert [i["ip"] for i in spawned] == ["10.9.0.5"]


def test_manual_scan_reconciles_too(scan_env, monkeypatch):
    config._static_cameras = [{"hostname": "bagno1", "name": "bagno1"}]
    state._set_resolved_ip("bagno1", "10.9.0.2")
    state._worker_tasks["10.9.0.2"] = object()
    spawned, torn = [], []
    monkeypatch.setattr(worker, "_spawn_worker", lambda info: spawned.append(info))

    async def _teardown(ip):
        torn.append(ip)
        state._worker_tasks.pop(ip, None)
        return True

    monkeypatch.setattr(worker, "_teardown_camera", _teardown)
    scan_env.devices = {"10.9.0.5": _dev("10.9.0.5", "bagno1")}
    scan_env.run(automatic=False)
    assert torn == ["10.9.0.2"] and [i["ip"] for i in spawned] == ["10.9.0.5"]


# ── state cache primitives ────────────────────────────────────────────────────────
def test_hostname_cache_reverse_lookup_and_rekey(hostname_env):
    state._set_resolved_ip("STANZA_11", "10.9.0.2")
    # spelled as configured (for diagnostics); keyed canonically (for matching)
    assert state._hostname_for_ip("10.9.0.2") == "STANZA_11"
    assert state._resolved_ip("stanza_11") == "10.9.0.2"
    assert state._hostname_for_ip("10.9.0.3") is None
    assert state._rekey_resolved_hostname("STANZA_11", "salotto") is True
    assert state._resolved_hostnames() == {"salotto": "10.9.0.2"}
    assert state._rekey_resolved_hostname("STANZA_11", "altro") is False
    assert state._drop_resolved_hostname("SALOTTO") is True
    assert state._resolved_hostnames() == {}
