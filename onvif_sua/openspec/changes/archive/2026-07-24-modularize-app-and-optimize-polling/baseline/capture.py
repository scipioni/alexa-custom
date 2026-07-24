#!/usr/bin/env python3
"""Reproducible pre/post-refactor baseline capture (change task 1.1).

Captures, from FIXED inputs so the run is identical every time:
  * the exact bytes of GET /, /login, /settings (via FastAPI TestClient with a
    fixed injected session), and
  * the ordered list of MQTT (topic, payload, qos, retain) publish calls emitted
    by the discovery + state functions for ONE fixed camera, recorded through a
    stub mqtt.Client (no broker).

Works against BOTH the pre-refactor monolith (`app`) and the post-refactor
package (`onvif_sua`) — it auto-detects which is importable. Run it before the
refactor to write the committed baseline, and after to diff against it.

Usage:  python capture.py <output_dir>   (default: this script's directory)
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture_settings.yaml"
CAM = "valigetta1"


def _point_settings_at_temp_copy() -> str:
    tmpdir = tempfile.mkdtemp(prefix="onvif-baseline-")
    dst = os.path.join(tmpdir, "settings.yaml")
    shutil.copy(FIXTURE, dst)
    os.environ["SETTINGS_FILE"] = dst
    return dst


class RecordingMqtt:
    """Minimal stand-in for a connected paho client: records publishes."""
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.calls.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})

    def is_connected(self):
        return True


def _load_target():
    """Return (cfg_mod, mqtt_mod, fastapi_app, session_mod). Prefers the package;
    falls back to the pre-refactor monolith `app`."""
    try:
        import importlib
        cfg_mod = importlib.import_module("onvif_sua.config")
        mqtt_mod = importlib.import_module("onvif_sua.mqtt")
        # `onvif_sua.web` re-exports the FastAPI instance as `app`; the session
        # helpers live in the real submodule `onvif_sua.web.app`.
        webpkg = importlib.import_module("onvif_sua.web")
        session_mod = importlib.import_module("onvif_sua.web.app")
        return cfg_mod, mqtt_mod, webpkg.app, session_mod
    except Exception:
        import app as m  # type: ignore
        return m, m, m.app, m


def capture(out_dir: Path):
    _point_settings_at_temp_copy()
    cfg_mod, mqtt_mod, fastapi_app, session_mod = _load_target()

    # Load settings from the fixture so _cfg (mqtt prefix etc.) is deterministic.
    cfg_mod._load_settings_yaml()

    # ── Pages ──────────────────────────────────────────────────────────────
    from fastapi.testclient import TestClient
    # A valid session cookie derived from the app's own (ephemeral) secret; the
    # pages are static so the token value never appears in the output bytes.
    token = session_mod._session_token()

    client = TestClient(fastapi_app)
    client.cookies.set("onvif_session", token)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, path in (("index", "/"), ("settings", "/settings")):
        r = client.get(path)
        (out_dir / f"page_{name}.html").write_text(r.text, encoding="utf-8")
    # login is unauthenticated — capture WITHOUT the session cookie.
    client_anon = TestClient(fastapi_app)
    (out_dir / "page_login.html").write_text(client_anon.get("/login").text, encoding="utf-8")

    # ── MQTT ───────────────────────────────────────────────────────────────
    stub = RecordingMqtt()
    mqtt_mod._mqtt_client = stub
    mqtt_mod._mqtt_discovered.clear()
    mqtt_mod._mqtt_detect_discovered.clear()
    mqtt_mod._mqtt_publish_discovery(CAM)
    mqtt_mod._mqtt_publish(CAM, "on")
    mqtt_mod._mqtt_publish(CAM, "off")
    mqtt_mod._mqtt_publish_detect_discovery(CAM)
    mqtt_mod._mqtt_publish_detection_ok(
        CAM, "on", {"stream_alive": True, "rule_enabled": True, "liveness_mode": "heartbeat"})
    mqtt_mod._mqtt_publish_detection_ok(
        CAM, "off", {"stream_alive": False, "rule_enabled": "unknown", "liveness_mode": "heartbeat"})
    (out_dir / "mqtt_calls.json").write_text(
        json.dumps(stub.calls, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[capture] wrote {len(stub.calls)} MQTT calls + 3 pages to {out_dir}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
    capture(out)
