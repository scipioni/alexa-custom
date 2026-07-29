"""_load_alarm_file hygiene on the persisted alarm state.

Two independent guards, both protecting the same failure — a persisted "on" that no
worker can ever clear, latching the global alarm (and the Home Assistant entity) ON:

1. Entries for cameras no longer in settings.yaml are dropped (the 'cucina' orphan bug).
2. An "on" older than the startup window is loaded as "off": _fire_stop only runs off a
   real `Stop` event, so a stale Start/Stop pair that completed while the service was
   down leaves nothing able to turn it off.
"""
import json
from datetime import datetime, timedelta

from onvif_sua import config, state, worker


def _write_alarm(tmp_path, data, *, age_s=0):
    """Write an alarm.json whose `saved_at` is `age_s` seconds in the past."""
    if age_s is not None:
        stamp = datetime.now() - timedelta(seconds=age_s)
        data = {"saved_at": stamp.isoformat(timespec="seconds"), **data}
    p = tmp_path / "alarm.json"
    p.write_text(json.dumps(data))
    return str(p)


def _configure(*names):
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {
        "credentials": {"port": 80},
        "list": [{"ip": f"10.0.0.{i}", "name": n} for i, n in enumerate(names, 1)],
    }


# ── guard 1: cameras no longer configured ─────────────────────────────────────────
def test_orphan_alarm_pruned(restore_globals, monkeypatch, tmp_path, capsys):
    # settings.yaml has only 'letto'; alarm.json has a stale 'cucina': 'on'
    _configure("letto")
    alarm_file = _write_alarm(tmp_path, {"cucina": "on", "letto": "off"})
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert "cucina" not in state._cam_alarms          # orphan dropped
        assert state._cam_alarms.get("letto") == "off"
        # global alarm is NOT latched on by the orphan
        assert state._alarms.get("Alarm uomo a terra") == "off"
    assert "non più configurata" in capsys.readouterr().out
    config._settings_doc.clear()


def test_configured_on_alarm_kept(restore_globals, monkeypatch, tmp_path):
    """A RECENT 'on' for a configured camera is adopted — a fall may still be in
    progress, and the camera's `Start` edge will not replay for this process."""
    _configure("letto")
    alarm_file = _write_alarm(tmp_path, {"letto": "on"}, age_s=10)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "on"
        assert state._alarms.get("Alarm uomo a terra") == "on"
    config._settings_doc.clear()


def test_no_prune_when_config_empty(restore_globals, monkeypatch, tmp_path):
    # Empty/absent config → conservative: keep entries (don't nuke a real alarm on a
    # transient parse hiccup). The freshness gate still applies, so use a recent stamp.
    config._settings_doc.clear()
    alarm_file = _write_alarm(tmp_path, {"cucina": "on"}, age_s=10)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("cucina") == "on"
    config._settings_doc.clear()


def test_configured_names_helper(restore_globals):
    _configure("letto", "salotto")
    assert config._configured_camera_names() == {"letto", "salotto"}
    config._settings_doc.clear()
    assert config._configured_camera_names() == set()


# ── guard 2: freshness of the persisted state ─────────────────────────────────────
def test_stale_on_is_loaded_as_off(restore_globals, monkeypatch, tmp_path, capsys):
    """The reported bug: an 'on' older than the window was republished to MQTT at boot
    and stayed active in Home Assistant with nothing able to clear it."""
    _configure("letto")
    alarm_file = _write_alarm(tmp_path, {"letto": "on"}, age_s=7 * 24 * 3600)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "off"
        assert state._alarms.get("Alarm uomo a terra") == "off"
    out = capsys.readouterr().out
    assert "stato 'on' scartato" in out and "letto" in out


def test_stale_off_is_kept_without_a_warning(restore_globals, monkeypatch, tmp_path, capsys):
    """Only 'on' is age-sensitive; a stale 'off' says nothing dangerous."""
    _configure("letto")
    alarm_file = _write_alarm(tmp_path, {"letto": "off"}, age_s=7 * 24 * 3600)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "off"
    assert "scartato" not in capsys.readouterr().out


def test_on_exactly_at_the_window_is_kept(restore_globals, monkeypatch, tmp_path):
    _configure("letto")
    max_age = float(config._cfg["serena_startup_alarm_max_age_s"])
    alarm_file = _write_alarm(tmp_path, {"letto": "on"}, age_s=int(max_age) - 5)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "on"
    config._settings_doc.clear()


def test_missing_saved_at_is_treated_as_stale(restore_globals, monkeypatch, tmp_path, capsys):
    """No timestamp means the age cannot be established, so an 'on' is not trusted."""
    _configure("letto")
    alarm_file = _write_alarm(tmp_path, {"letto": "on"}, age_s=None)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "off"
    assert "senza timestamp valido" in capsys.readouterr().out
    config._settings_doc.clear()


def test_unparseable_saved_at_is_treated_as_stale(restore_globals, monkeypatch, tmp_path):
    _configure("letto")
    p = tmp_path / "alarm.json"
    p.write_text(json.dumps({"saved_at": "not-a-timestamp", "letto": "on"}))
    monkeypatch.setattr(worker, "ALARM_FILE", str(p))

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "off"
    config._settings_doc.clear()


def test_window_follows_the_configured_value(restore_globals, monkeypatch, tmp_path):
    """The gate uses the same knob as the Serena startup adoption, so widening it keeps
    an older alarm — the two can no longer disagree about the same state."""
    _configure("letto")
    config._cfg["serena_startup_alarm_max_age_s"] = 86400.0
    alarm_file = _write_alarm(tmp_path, {"letto": "on"}, age_s=3600)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "on"
    config._settings_doc.clear()


def test_stale_and_fresh_entries_are_handled_independently(restore_globals, monkeypatch,
                                                           tmp_path):
    """One timestamp covers the whole file, so a stale file discards every 'on' in it —
    but 'off' entries and the camera set are untouched."""
    _configure("letto", "salotto")
    alarm_file = _write_alarm(tmp_path, {"letto": "on", "salotto": "off"},
                              age_s=7 * 24 * 3600)
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms == {"letto": "off", "salotto": "off"}
        assert state._alarms.get("Alarm uomo a terra") == "off"
    config._settings_doc.clear()
