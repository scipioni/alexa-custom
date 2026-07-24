"""Regression: _load_alarm_file prunes persisted alarm entries for cameras that are
no longer configured, so a renamed/removed camera cannot latch the global alarm ON
(the 'cucina' orphan bug)."""
import json

from onvif_sua import config, state, worker


def _write_alarm(tmp_path, data):
    p = tmp_path / "alarm.json"
    p.write_text(json.dumps(data))
    return str(p)


def _configure(*names):
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {
        "credentials": {"port": 80},
        "list": [{"ip": f"10.0.0.{i}", "name": n} for i, n in enumerate(names, 1)],
    }


def test_orphan_alarm_pruned(restore_globals, monkeypatch, tmp_path, capsys):
    # settings.yaml has only 'letto'; alarm.json has a stale 'cucina': 'on'
    _configure("letto")
    alarm_file = _write_alarm(tmp_path, {"saved_at": "2026-07-24T15:07:48",
                                         "cucina": "on", "letto": "off"})
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
    _configure("letto")
    alarm_file = _write_alarm(tmp_path, {"saved_at": "2026-07-24T15:07:48", "letto": "on"})
    monkeypatch.setattr(worker, "ALARM_FILE", alarm_file)

    worker._load_alarm_file()

    with state._lock:
        assert state._cam_alarms.get("letto") == "on"
        assert state._alarms.get("Alarm uomo a terra") == "on"
    config._settings_doc.clear()


def test_no_prune_when_config_empty(restore_globals, monkeypatch, tmp_path):
    # Empty/absent config → conservative: keep entries (don't nuke a real alarm on a
    # transient parse hiccup).
    config._settings_doc.clear()
    alarm_file = _write_alarm(tmp_path, {"saved_at": "2026-07-24T15:07:48", "cucina": "on"})
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
