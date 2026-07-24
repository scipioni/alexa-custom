"""Task 5.1c (web layer): api_rename_camera / api_save_camera reject a name that
contains 'camera' or collides (after voice normalization) with another camera, with
a 4xx + detail, and do not persist it."""
import asyncio
import json

import pytest

from onvif_sua import config, state, worker
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


@pytest.fixture
def two_cams(serena_cfg, monkeypatch):
    """Two configured cameras in _settings_doc + a live entry for the one being edited.
    _save_settings_yaml is stubbed so no real file is written."""
    config._settings_doc.clear()
    config._settings_doc["cameras"] = {"credentials": {"port": 80}, "list": [
        {"ip": "10.0.0.1", "name": "salotto-1"},
        {"ip": "10.0.0.2", "name": "cucina"},
    ]}
    monkeypatch.setattr(config, "_save_settings_yaml", lambda: None)
    yield
    config._settings_doc.clear()


# ── rename ────────────────────────────────────────────────────────────────────────
def test_rename_reserved_word_rejected(two_cams):
    resp = _run(routes.api_rename_camera("10.0.0.2", _FakeReq({"name": "Camera 0"})))
    assert resp.status_code == 400
    assert "camera" in _body(resp)["detail"].lower()
    # not persisted: cucina still present, no 'camera' entry
    names = [e["name"] for e in config._settings_doc["cameras"]["list"]]
    assert "cucina" in names and not any("camera" in n.lower() for n in names)


def test_rename_voice_collision_rejected(two_cams):
    # rename cucina (10.0.0.2) to 'salotto_1' → collides with salotto-1 (10.0.0.1)
    resp = _run(routes.api_rename_camera("10.0.0.2", _FakeReq({"name": "salotto_1"})))
    assert resp.status_code == 400
    assert "normalizzazione" in _body(resp)["detail"]
    names = [e["name"] for e in config._settings_doc["cameras"]["list"]]
    assert names == ["salotto-1", "cucina"]   # unchanged


def test_rename_telecamera_rejected(two_cams):
    resp = _run(routes.api_rename_camera("10.0.0.2", _FakeReq({"name": "telecamera-2"})))
    assert resp.status_code == 400


# ── save ────────────────────────────────────────────────────────────────────────
def test_save_reserved_word_rejected(two_cams, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    with state._lock:
        state._cameras["10.0.0.5"] = {"name": "provvisoria", "port": 80}
    resp = _run(routes.api_save_camera("10.0.0.5", _FakeReq({"name": "camera-nuova"})))
    assert resp.status_code == 400
    assert "camera" in _body(resp)["detail"].lower()
    # not persisted
    ips = [e["ip"] for e in config._settings_doc["cameras"]["list"]]
    assert "10.0.0.5" not in ips


def test_save_voice_collision_rejected(two_cams, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    with state._lock:
        state._cameras["10.0.0.5"] = {"name": "provvisoria", "port": 80}
    resp = _run(routes.api_save_camera("10.0.0.5", _FakeReq({"name": "salotto_1"})))
    assert resp.status_code == 400
    assert "normalizzazione" in _body(resp)["detail"]
    ips = [e["ip"] for e in config._settings_doc["cameras"]["list"]]
    assert "10.0.0.5" not in ips


# ── simulate button drives the Serena bridge (end-to-end test aid) ────────────────
def test_simulate_on_emits_serena_trigger(fake_mqtt, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    monkeypatch.setattr(routes, "_write_alarm_file", lambda: None)
    with state._lock:
        state._cameras["10.0.0.7"] = worker._new_cam("10.0.0.7", "soggiorno")
    resp = _run(routes.api_simulate_camera("10.0.0.7", _FakeReq({"on": True})))
    assert resp.status_code == 200
    trig = [c for c in fake_mqtt.calls if c[0].endswith("/trigger/run")]
    assert len(trig) == 1 and trig[0][1] == "caduta soggiorno"


def test_simulate_off_no_trigger(fake_mqtt, monkeypatch):
    monkeypatch.setattr(routes, "_valid_session", lambda req: True)
    monkeypatch.setattr(routes, "_write_alarm_file", lambda: None)
    with state._lock:
        state._cameras["10.0.0.7"] = worker._new_cam("10.0.0.7", "soggiorno")
    resp = _run(routes.api_simulate_camera("10.0.0.7", _FakeReq({"on": False})))
    assert resp.status_code == 200
    trig = [c for c in fake_mqtt.calls if c[0].endswith("/trigger/run")]
    assert trig == []
