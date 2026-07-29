"""Shared fixtures for the Serena-fall-bridge test suite.

The production code keeps module-global state (`config._cfg`, `mqtt._mqtt_client`,
the serena one-shot flags, the `state._cameras` registry). These fixtures snapshot
and restore that state around each test so tests stay independent, and provide a
`FakeMqtt` client plus a fake Dahua attach-stream harness for driving the real
`_dahua_cgi_thread` without a socket.
"""
import threading

import pytest

from onvif_sua import config, mqtt, state, worker


# ── serena config defaults (post-normalization) applied per test ─────────────────
_SERENA_TEST_DEFAULTS = {
    "mqtt_host": "localhost",
    "mqtt_prefix": "onvif",
    "serena_enabled": True,
    "serena_topic_prefix": "alexa",
    "serena_node_id": "serena",
    "serena_command_template": "caduta_{cam_name}",
    "serena_announce_ready": True,
    "serena_announce_template": "sensore uomo a terra {cam_name} attivo",
    "serena_announce_fault": False,
    "serena_announce_fault_template": "attenzione, sensore uomo a terra {cam_name} non attivo",
    "serena_announce_fault_interval_s": 300.0,
    "serena_announce_fault_grace_s": 60.0,
    "serena_startup_alarm_max_age_s": 300.0,
}


class FakeMqtt:
    """Minimal stand-in for the paho client: records publishes and reports a
    configurable connection state. `publish` returns a handle with a no-op
    `wait_for_publish`."""

    def __init__(self, connected=True):
        self._connected = connected
        self.calls = []   # list of (topic, payload, qos, retain)

    def is_connected(self):
        return self._connected

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.calls.append((topic, payload, qos, retain))

        class _Info:
            def wait_for_publish(self_inner, timeout=None):
                return None

        return _Info()

    # convenience for assertions
    def topics(self, suffix):
        return [c for c in self.calls if c[0].endswith(suffix)]


@pytest.fixture(autouse=True)
def isolate_settings_file(tmp_path, monkeypatch):
    """Point `config.SETTINGS_FILE` at a throwaway path for EVERY test.

    Several code paths persist settings as a side effect (`_config_add_camera`,
    `_config_remove_camera`, `api_config_post`), and stubbing `config._save_settings_yaml`
    is not enough: `web/routes.py` binds its own reference at import
    (`from ..config import _save_settings_yaml`), so patching the attribute on `config`
    leaves the routes copy live. A test that reaches an unstubbed save would otherwise
    overwrite the developer's real settings.yaml — including the camera list — with
    whatever `_cfg`/`_settings_doc` happen to hold. A test that needs to inspect a written
    file just sets SETTINGS_FILE itself; its own monkeypatch wins over this one.
    """
    monkeypatch.setattr(config, "SETTINGS_FILE", str(tmp_path / "settings.yaml"))


@pytest.fixture
def restore_globals():
    """Snapshot/restore the mutated module globals around a test."""
    cfg_snapshot = dict(config._cfg)
    static_snapshot = list(config._static_cameras)
    saved_client = mqtt._mqtt_client
    saved_flags = (mqtt._serena_warned_no_node, mqtt._serena_logged_target,
                   mqtt._serena_bridge_discovered)
    yield
    config._cfg.clear()
    config._cfg.update(cfg_snapshot)
    config._static_cameras = static_snapshot
    mqtt._mqtt_client = saved_client
    (mqtt._serena_warned_no_node, mqtt._serena_logged_target,
     mqtt._serena_bridge_discovered) = saved_flags
    with state._lock:
        state._cameras.clear()
        state._cam_alarms.clear()
        state._alarms.clear()


@pytest.fixture
def serena_cfg(restore_globals):
    """Apply the serena test defaults to `_cfg` and reset the one-shot flags."""
    config._cfg.update(_SERENA_TEST_DEFAULTS)
    mqtt._serena_warned_no_node = False
    mqtt._serena_logged_target = False
    mqtt._serena_bridge_discovered = False
    return config._cfg


@pytest.fixture
def fake_mqtt(serena_cfg):
    """Install a connected FakeMqtt client on the mqtt module."""
    cli = FakeMqtt(connected=True)
    mqtt._mqtt_client = cli
    return cli


# ── fake Dahua attach-stream harness ─────────────────────────────────────────────
_STOP = object()   # sentinel line → EOF + set stop_event


class _FakeRaw:
    """resp.raw stand-in: readline() pulls queued lines, then signals EOF and stops
    the thread. A line equal to `_STOP` also signals EOF."""

    def __init__(self, lines, stop_event):
        self._it = iter(lines)
        self._stop = stop_event

    def readline(self):
        try:
            item = next(self._it)
        except StopIteration:
            self._stop.set()
            return b""
        if item is _STOP:
            self._stop.set()
            return b""
        return item.encode() if isinstance(item, str) else item


class _FakeResp:
    def __init__(self, lines, stop_event, status=200):
        self.status_code = status
        self.raw = _FakeRaw(lines, stop_event)

    def close(self):
        pass


@pytest.fixture
def immediate_timer(monkeypatch):
    """Replace threading.Timer in worker so the 10 s alarm-stop fires synchronously
    on .start(), letting re-arm be tested without waiting."""

    class _ImmediateTimer:
        def __init__(self, delay, fn):
            self._fn = fn
            self.daemon = False

        def start(self):
            self._fn()

        def cancel(self):
            pass

    monkeypatch.setattr(worker.threading, "Timer", _ImmediateTimer)
    return _ImmediateTimer


@pytest.fixture
def run_cgi(monkeypatch):
    """Return a runner that drives the REAL worker._dahua_cgi_thread over a scripted
    list of attach-stream lines, with requests.get faked. Runs synchronously (the
    fake stream reaches EOF and sets the stop event)."""
    import requests

    def _runner(ip, name, lines, *, static=True):
        # Ensure a camera entry exists and is past the auth gate.
        with state._lock:
            state._cameras.setdefault(ip, worker._new_cam(ip, name))
            state._cameras[ip]["_static"] = static
        state._auth_gate.mark_success(ip)
        stop_event = threading.Event()

        def _fake_get(url, auth=None, stream=False, timeout=None):
            return _FakeResp(list(lines), stop_event)

        monkeypatch.setattr(requests, "get", _fake_get)
        worker._dahua_cgi_thread(ip, 80, "admin", "pw", name, stop_event)

    return _runner


def start_line():
    return "Code=TumbleDetection;action=Start"


def stop_line():
    return "Code=TumbleDetection;action=Stop"
