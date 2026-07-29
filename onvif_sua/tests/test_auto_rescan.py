"""Automatic periodic rescan driven by `scan.rescan_time_interval`.

The scanner was deliberately manual-only: it spawns a worker for every ONVIF device it
finds, so running it on a timer must not (a) run at all unless the interval is set,
(b) double a scan already in progress, or (c) quietly undo an operator's removal.
"""
import asyncio
import json

import pytest

from onvif_sua import config, scan, state, worker
from onvif_sua.web import routes


class _FakeReq:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


def _run(coro):
    return asyncio.run(coro)


def _body(resp):
    return json.loads(resp.body)


# The genuine writer, captured before any fixture stubs it out, for the one test that
# needs to inspect what actually lands on disk (into tmp_path, never the real file).
_real_save_settings_yaml = config._save_settings_yaml


@pytest.fixture
def rescan_env(restore_globals, monkeypatch):
    """Neutral scan state: nothing running, a known last-scan timestamp, no writes."""
    monkeypatch.setattr(scan, "_scan_active", False)
    monkeypatch.setattr(scan, "_last_scan_ts", 1000.0)
    # Both references: config's own, and the copy web/routes.py bound at import time
    # (api_config_post calls that one, so patching only config would still hit the disk).
    monkeypatch.setattr(config, "_save_settings_yaml", lambda: None)
    monkeypatch.setattr(routes, "_save_settings_yaml", lambda: None)
    monkeypatch.setattr(config, "_rescan_floor_warned", False)
    state._operator_removed.clear()
    config._cfg["rescan_time_interval"] = 0
    yield
    state._operator_removed.clear()


# ── config: interval parsing, disabled-by-default, safety floor ───────────────────
def test_disabled_by_default(rescan_env):
    assert config._rescan_interval() == 0.0


@pytest.mark.parametrize("raw", [0, "0", -5, "-5", "", "abc", None])
def test_non_positive_or_junk_disables(rescan_env, raw):
    config._cfg["rescan_time_interval"] = raw
    assert config._rescan_interval() == 0.0


@pytest.mark.parametrize("raw,expected", [(60, 60.0), ("600", 600.0), (3600, 3600.0)])
def test_valid_intervals_pass_through(rescan_env, raw, expected):
    config._cfg["rescan_time_interval"] = raw
    assert config._rescan_interval() == expected


def test_interval_below_the_floor_is_clamped_and_warned_once(rescan_env, capsys):
    config._cfg["rescan_time_interval"] = 5
    assert config._rescan_interval() == config._RESCAN_INTERVAL_FLOOR
    assert "sotto il minimo" in capsys.readouterr().out
    assert config._rescan_interval() == config._RESCAN_INTERVAL_FLOOR
    assert "sotto il minimo" not in capsys.readouterr().out   # not on every check


def test_interval_round_trips_through_a_save(rescan_env, monkeypatch, tmp_path):
    import yaml
    target = tmp_path / "written.yaml"
    monkeypatch.setattr(config, "SETTINGS_FILE", str(target))
    config._cfg["rescan_time_interval"] = 900
    _real_save_settings_yaml()
    doc = yaml.safe_load(target.read_text())
    assert doc["scan"]["rescan_time_interval"] == 900


def test_interval_is_read_from_the_settings_scan_block(rescan_env, monkeypatch, tmp_path):
    target = tmp_path / "settings.yaml"
    target.write_text("scan:\n  subnet: 10.0.0.0/24\n  rescan_time_interval: 1200\n")
    monkeypatch.setattr(config, "SETTINGS_FILE", str(target))
    config._load_settings_yaml()
    assert config._rescan_interval() == 1200.0


# ── the due-check: the three gates ────────────────────────────────────────────────
def test_not_due_while_disabled_even_after_a_long_time(rescan_env):
    config._cfg["rescan_time_interval"] = 0
    assert worker._auto_rescan_due(1000.0 + 86400) is False


def test_not_due_before_the_interval_has_elapsed(rescan_env):
    config._cfg["rescan_time_interval"] = 600
    assert worker._auto_rescan_due(1000.0 + 599) is False


def test_due_exactly_at_the_interval(rescan_env):
    config._cfg["rescan_time_interval"] = 600
    assert worker._auto_rescan_due(1000.0 + 600) is True


def test_not_due_while_a_scan_is_already_running(rescan_env, monkeypatch):
    config._cfg["rescan_time_interval"] = 600
    monkeypatch.setattr(scan, "_scan_active", True)
    assert worker._auto_rescan_due(1000.0 + 6000) is False


def test_a_manual_scan_pushes_the_next_automatic_one_a_full_interval_out(rescan_env, monkeypatch):
    """The interval is measured from the last scan, not from a fixed tick."""
    config._cfg["rescan_time_interval"] = 600
    assert worker._auto_rescan_due(1000.0 + 600) is True
    monkeypatch.setattr(scan, "_last_scan_ts", 1000.0 + 590)   # a manual scan just ran
    assert worker._auto_rescan_due(1000.0 + 600) is False
    assert worker._auto_rescan_due(1000.0 + 590 + 600) is True


# ── the scan itself: automatic vs manual treatment of removed cameras ─────────────
@pytest.fixture
def sweeping(rescan_env, monkeypatch):
    """Run the REAL _subnet_scan_once over a synthetic 2-host subnet with a stubbed
    per-host probe, recording which cameras got a worker."""

    class _S:
        def __init__(self):
            self.spawned = []
            self.devices = {}          # ip → probe result

        async def _probe(self, ip):
            return self.devices.get(ip)

        def run(self, automatic):
            _run(scan._subnet_scan_once(automatic=automatic))
            return [c["ip"] for c in self.spawned]

    s = _S()
    monkeypatch.setattr(scan, "_probe_ip", s._probe)
    monkeypatch.setattr(scan, "_spawn_worker", lambda cam: s.spawned.append(cam))
    monkeypatch.setattr(config, "_password_placeholder_flags",
                        lambda: {"cameras": False, "scan": False})
    config._cfg["scan_subnet"] = "10.9.0.0/30"          # hosts .1 and .2
    s.devices = {
        "10.9.0.1": {"ip": "10.9.0.1", "name": "a", "hostname": "a",
                     "user": "admin", "pass": "pw", "port": 80},
        "10.9.0.2": {"ip": "10.9.0.2", "name": "b", "hostname": "b",
                     "user": "admin", "pass": "pw", "port": 80},
    }
    yield s
    with state._lock:
        state._cameras.clear()


def test_automatic_scan_spawns_workers_for_new_devices(sweeping):
    assert sorted(sweeping.run(automatic=True)) == ["10.9.0.1", "10.9.0.2"]


def test_automatic_scan_does_not_readd_an_operator_removed_camera(sweeping, capsys):
    state._operator_removed.add("10.9.0.2")
    assert sweeping.run(automatic=True) == ["10.9.0.1"]
    assert "rimosse dall'operatore" in capsys.readouterr().out


def test_skipped_camera_is_reported_in_the_dashboard_event_log(sweeping):
    """The operator sees the camera online-but-absent; the reason must be visible in the
    web log, not only on the console."""
    state._operator_removed.add("10.9.0.2")
    with state._lock:
        state._event_log.clear()
    sweeping.run(automatic=True)
    with state._lock:
        rows = [e for e in state._event_log if e["topic"] == "Scanner/RemovedNotReadded"]
    assert len(rows) == 1
    assert rows[0]["ip"] == "10.9.0.2"
    assert rows[0]["name"] == "b"                      # the name the device reports
    assert rows[0]["data"]["motivo"] == "rimossa dall'operatore"
    assert "rescan manuale" in rows[0]["data"]["azione"]
    assert rows[0]["ts"]                               # timestamped like any event


def test_one_log_row_per_skipped_camera(sweeping):
    state._operator_removed.update({"10.9.0.1", "10.9.0.2"})
    with state._lock:
        state._event_log.clear()
    assert sweeping.run(automatic=True) == []
    with state._lock:
        ips = sorted(e["ip"] for e in state._event_log
                     if e["topic"] == "Scanner/RemovedNotReadded")
    assert ips == ["10.9.0.1", "10.9.0.2"]


def test_manual_scan_logs_no_skip_event(sweeping):
    """A manual rescan re-adds everything, so there is nothing to report."""
    state._operator_removed.add("10.9.0.2")
    with state._lock:
        state._event_log.clear()
    sweeping.run(automatic=False)
    with state._lock:
        assert [e for e in state._event_log
                if e["topic"] == "Scanner/RemovedNotReadded"] == []


def test_skip_event_does_not_need_a_live_camera_row(sweeping):
    """The camera was removed, so `_cameras` has no entry for it — recording the event
    must not depend on one."""
    state._operator_removed.add("10.9.0.2")
    with state._lock:
        state._cameras.pop("10.9.0.2", None)
        state._event_log.clear()
    sweeping.run(automatic=True)
    with state._lock:
        assert any(e["ip"] == "10.9.0.2" for e in state._event_log)


def test_manual_scan_still_readds_a_removed_camera(sweeping):
    """A manual rescan is an explicit request for a full refresh — unchanged behaviour."""
    state._operator_removed.add("10.9.0.2")
    assert sorted(sweeping.run(automatic=False)) == ["10.9.0.1", "10.9.0.2"]
    assert state._operator_removed == set()      # cleared by the manual scan


def test_every_scan_stamps_the_last_scan_timestamp(sweeping, monkeypatch):
    monkeypatch.setattr(scan, "_last_scan_ts", 0.0)
    sweeping.run(automatic=True)
    assert scan._last_scan_ts > 0.0


def test_a_suppressed_scan_still_stamps_the_timestamp(rescan_env, monkeypatch):
    """Placeholder password → the scan is refused. It must still stamp the clock, or the
    automatic loop would retry (and log) on every single tick."""
    monkeypatch.setattr(config, "_password_placeholder_flags",
                        lambda: {"cameras": True, "scan": True})
    monkeypatch.setattr(scan, "_last_scan_ts", 0.0)
    _run(scan._subnet_scan_once(automatic=True))
    assert scan._last_scan_ts > 0.0


def test_an_invalid_subnet_stamps_the_timestamp(rescan_env, monkeypatch):
    monkeypatch.setattr(config, "_password_placeholder_flags",
                        lambda: {"cameras": False, "scan": False})
    monkeypatch.setattr(scan, "_last_scan_ts", 0.0)
    config._cfg["scan_subnet"] = "non-una-subnet"
    _run(scan._subnet_scan_once(automatic=True))
    assert scan._last_scan_ts > 0.0
    assert scan._scan_active is False


# ── removal / save bookkeeping through the API ────────────────────────────────────
def test_removing_a_camera_marks_it_for_the_automatic_scan(rescan_env, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": [
        {"ip": "10.9.0.2", "name": "cucina"}]}
    config._static_cameras = [{"ip": "10.9.0.2", "name": "cucina"}]
    _run(routes.api_remove_camera("10.9.0.2", _FakeReq({})))
    assert "10.9.0.2" in state._operator_removed
    config._settings_doc.clear()


def test_saving_a_camera_clears_the_removed_mark(rescan_env, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": []}
    config._static_cameras = []
    state._operator_removed.add("10.9.0.2")
    with state._lock:
        cam = worker._new_cam("10.9.0.2", "provvisoria", "admin", "pw", 80)
        cam["onvif_hostname"] = "STANZA_9"
        state._cameras["10.9.0.2"] = cam
    resp = _run(routes.api_save_camera("10.9.0.2", _FakeReq({"name": "cucina"})))
    assert resp.status_code == 200
    assert "10.9.0.2" not in state._operator_removed
    config._settings_doc.clear()
    with state._lock:
        state._hostname_ips.clear()


# ── status + config API surface ───────────────────────────────────────────────────
def test_status_reports_the_interval_and_the_countdown(rescan_env, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    config._cfg["rescan_time_interval"] = 600
    monkeypatch.setattr(routes.time, "time", lambda: 1000.0 + 100)
    body = _body(routes.api_status(_FakeReq({})))
    assert body["rescan_interval"] == 600.0
    assert body["rescan_in"] == 500.0


def test_status_reports_none_when_disabled(rescan_env, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    body = _body(routes.api_status(_FakeReq({})))
    assert body["rescan_interval"] == 0.0
    assert body["rescan_in"] is None


def test_config_post_accepts_and_returns_the_effective_interval(rescan_env, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    monkeypatch.setattr(routes, "_mqtt_init", lambda: None)
    resp = _run(routes.api_config_post(_FakeReq({"rescan_time_interval": 900})))
    assert resp.status_code == 200
    assert _body(resp)["rescan_time_interval"] == 900.0
    assert config._rescan_interval() == 900.0


def test_config_post_rejects_a_negative_interval(rescan_env, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    monkeypatch.setattr(routes, "_mqtt_init", lambda: None)
    resp = _run(routes.api_config_post(_FakeReq({"rescan_time_interval": -1})))
    assert resp.status_code == 400
    assert "negativo" in _body(resp)["detail"]
