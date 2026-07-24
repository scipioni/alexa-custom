"""MQTT discovery + state publishing (Home Assistant): fall binary_sensor and the
detection_ok/fall_sensor_online liveness sensor. Topics/payloads are preserved
verbatim. Owns the live paho client (`_mqtt_client`)."""
import json
from typing import Optional

from . import config
from .config import _cfg, _serena_voice_name
from .state import _lock, _cameras


# ── MQTT client ───────────────────────────────────────────────────────────────
_mqtt_client = None
_mqtt_discovered: set[str] = set()
def _slug(cam_name: str) -> str:
    return cam_name.lower().replace(" ", "_").replace("-", "_")
def _mqtt_unique_id(cam_name: str) -> str:
    return "onvif_fall_" + _slug(cam_name)
def _mqtt_publish_discovery(cam_name: str):
    if not _mqtt_client:
        return
    prefix = _cfg["mqtt_prefix"]
    uid    = _mqtt_unique_id(cam_name)
    payload = {
        "name":                  "Rilevamento caduta",
        # HA appends the device-name slug to object_id, so the entity_id becomes
        # binary_sensor.<object_id>_<cam_slug>. Keep the cam name OUT of object_id
        # here or it repeats (…_valigetta1_valigetta1).
        "object_id":             "rilevamento_caduta",
        "unique_id":             uid,
        "device_class":          "safety",
        "icon":                  "mdi:account-injury",
        "state_topic":           f"{prefix}/{cam_name}/alarms/fall",
        "payload_on":            "on",
        "payload_off":           "off",
        "expire_after":          120,
        "device": {
            "identifiers":  [uid],
            "name":         cam_name,
            "model":        "Fall Detection",
            "manufacturer": "Dahua ONVIF",
        },
    }
    try:
        _mqtt_client.publish(
            f"homeassistant/binary_sensor/{uid}/config",
            json.dumps(payload), qos=1, retain=True
        )
        _mqtt_discovered.add(cam_name)
        print(f"[mqtt] HA discovery: {cam_name}", flush=True)
    except Exception as e:
        print(f"[mqtt] discovery errore: {e}", flush=True)
def _mqtt_stop():
    global _mqtt_client
    if _mqtt_client:
        try:
            _mqtt_client.loop_stop()
            _mqtt_client.disconnect()
        except Exception:
            pass
        _mqtt_client = None
        _mqtt_discovered.clear()
        # Re-arm the Serena bridge one-shots so a reinit (config change) re-logs the
        # target and re-publishes the diagnostic discovery.
        global _serena_logged_target, _serena_bridge_discovered
        _serena_logged_target = False
        _serena_bridge_discovered = False
def _mqtt_init():
    global _mqtt_client
    _mqtt_stop()
    host = _cfg.get("mqtt_host", "")
    if not host:
        return
    try:
        import paho.mqtt.client as mqtt

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print(f"[mqtt] connesso a {host}:{_cfg['mqtt_port']}", flush=True)
                for cn in list(_mqtt_discovered):
                    _mqtt_publish_discovery(cn)
                # Serena bridge: log the resolved target once (commissioning) and
                # (re)publish the retained health diagnostic on every (re)connect.
                _serena_log_target_once()
                _mqtt_publish_serena_bridge_status()
            else:
                print(f"[mqtt] rc={rc}", flush=True)

        c = mqtt.Client(client_id="onvif-events", clean_session=True)
        if _cfg.get("mqtt_user"):
            c.username_pw_set(_cfg["mqtt_user"], _cfg.get("mqtt_pass", ""))
        c.on_connect = on_connect
        c.reconnect_delay_set(min_delay=2, max_delay=60)
        c.connect_async(host, int(_cfg["mqtt_port"]), keepalive=60)
        c.loop_start()
        _mqtt_client = c
        print(f"[mqtt] avvio {host}:{_cfg['mqtt_port']} prefix={_cfg['mqtt_prefix']}", flush=True)
    except Exception as e:
        print(f"[mqtt] init fallita: {e}", flush=True)
def _mqtt_publish(cam_name: str, state: str):
    if not _mqtt_client:
        return
    if cam_name not in _mqtt_discovered:
        _mqtt_publish_discovery(cam_name)
    topic = f"{_cfg['mqtt_prefix']}/{cam_name}/alarms/fall"
    try:
        _mqtt_client.publish(topic, payload=state, qos=1, retain=True)
        print(f"[mqtt] {topic} → {state}", flush=True)
    except Exception as e:
        print(f"[mqtt] publish errore: {e}", flush=True)
# ── detection_ok liveness sensor (heartbeat-alive AND rule-enabled) ─────────────
_mqtt_detect_discovered: set[str] = set()
def _mqtt_unique_id_detect(cam_name: str) -> str:
    return "onvif_detect_ok_" + _slug(cam_name)
def _mqtt_publish_detect_discovery(cam_name: str):
    if not _mqtt_client or cam_name in _mqtt_detect_discovered:
        return
    prefix = _cfg["mqtt_prefix"]
    uid    = _mqtt_unique_id_detect(cam_name)
    payload = {
        "name":                  "Rilevamento attivo",
        # HA appends _<cam_slug>; keep cam name out of object_id (see fall sensor).
        "object_id":             "rilevamento_attivo",
        "unique_id":             uid,
        "device_class":          "connectivity",
        "icon":                  "mdi:shield-check",
        "state_topic":           f"{prefix}/{cam_name}/camera_status/fall_sensor_online",
        "json_attributes_topic": f"{prefix}/{cam_name}/camera_status/fall_sensor_online/attrs",
        "payload_on":            "on",
        "payload_off":           "off",
        "expire_after":          config.DETECTION_EXPIRE,
        "device": {
            "identifiers":  [_mqtt_unique_id(cam_name)],
            "name":         cam_name,
            "model":        "Fall Detection",
            "manufacturer": "Dahua ONVIF",
        },
    }
    try:
        _mqtt_client.publish(
            f"homeassistant/binary_sensor/{uid}/config",
            json.dumps(payload), qos=1, retain=True
        )
        _mqtt_detect_discovered.add(cam_name)
        print(f"[mqtt] detect_ok discovery: {cam_name}", flush=True)
    except Exception as e:
        print(f"[mqtt] detect_ok discovery errore: {e}", flush=True)
def _mqtt_publish_detection_ok(cam_name: str, working_state: str, attrs: Optional[dict] = None):
    """working_state: 'on' = rilevamento caduta ATTIVO/funzionante | 'off' = non attivo.

    Pubblicato con polarità intuitiva sul topic `.../camera_status/fall_sensor_online`
    (device_class: connectivity → `on` = online/attivo, `off` = offline). Nessuna
    inversione, a differenza del vecchio sensore `detection_ok`."""
    if not _mqtt_client:
        return
    _mqtt_publish_detect_discovery(cam_name)
    prefix = _cfg["mqtt_prefix"]
    base = f"{prefix}/{cam_name}/camera_status/fall_sensor_online"
    try:
        _mqtt_client.publish(base, payload=working_state, qos=1, retain=True)
        if attrs is not None:
            _mqtt_client.publish(f"{base}/attrs", json.dumps(attrs), qos=1, retain=True)
        print(f"[mqtt] fall_sensor_online {cam_name} → {working_state} "
              f"(rilevamento {'ATTIVO' if working_state=='on' else 'NON attivo'})", flush=True)
    except Exception as e:
        print(f"[mqtt] fall_sensor_online publish errore: {e}", flush=True)
def _compute_detection_ok(stream_alive: bool, rule_enabled) -> str:
    """Tri-state truth table: on iff stream alive AND rule not confirmed-disabled.

    rule_enabled ∈ {True, False, "unknown"}. 'unknown' does NOT force off.
    """
    if stream_alive and rule_enabled is not False:
        return "on"
    return "off"
def _refresh_detection_ok(ip: str):
    """Recompute detection_ok for a camera under the lock; publish (outside the
    lock) only when the resulting on/off value changed. Safe to call from either
    the attach-stream OS thread or the asyncio rule-check task."""
    announce_now = False
    with _lock:
        cam = _cameras.get(ip)
        if not cam:
            return
        if not cam.get("_static"):
            return   # detection_ok is published only for statically-configured cameras
        name        = cam.get("name", ip)
        simulated    = bool(cam.get("simulated"))
        # While simulated, report the detector as healthy regardless of the real
        # stream/rule state (which stays down for absent hardware).
        stream_alive = True if simulated else bool(cam.get("stream_alive", False))
        rule_enabled = True if simulated else cam.get("rule_enabled", "unknown")
        new_state   = _compute_detection_ok(stream_alive, rule_enabled)
        prev_state  = cam.get("detection_ok")
        cam["detection_ok"] = new_state
        changed = (new_state != prev_state)
        attrs = {
            "stream_alive": stream_alive,
            "rule_enabled": rule_enabled if rule_enabled != "unknown" else "unknown",
            "liveness_mode": config.LIVENESS_MODE,
        }
        # Serena active announcement: fire once per camera per process the first time
        # it is CONFIRMED-WORKING (stream alive AND rule_enabled is True — NOT merely
        # detection_ok=='on', which is also 'on' while rule is 'unknown'). Uses the
        # shared predicate (reentrant _lock) so it can never disagree with the fault
        # driver. The guard set under the lock makes it exactly-once.
        if not cam.get("serena_announced") and _camera_working(ip):
            cam["serena_announced"] = True
            announce_now = True
    if changed:
        _mqtt_publish_detection_ok(name, new_state, attrs)
    if announce_now:
        _mqtt_announce_serena_active(name)
# ── Serena fall-alarm bridge ─────────────────────────────────────────────────────
# Forward a fall-start (and opt-in sensor active/fault announcements) to Serena's
# MQTT command topics, reusing this module's already-connected paho client. Every
# helper is fault-isolated: a None client is a silent no-op and no exception ever
# propagates into the detection loop (spec "Emit never disrupts fall detection").
_serena_warned_no_node = False   # one-shot warning guard (enabled but node_id empty)
_serena_logged_target  = False   # one-shot commissioning log (A)
_serena_bridge_discovered = False   # HA diagnostic discovery published once


def _serena_preconditions_ok() -> bool:
    """True when the bridge is enabled, a broker host is configured, and node_id is
    non-empty. Logs a one-shot warning when enabled but node_id is missing."""
    global _serena_warned_no_node
    if not _cfg.get("serena_enabled"):
        return False
    if not _cfg.get("mqtt_host"):
        return False
    if not _cfg.get("serena_node_id"):
        if not _serena_warned_no_node:
            _serena_warned_no_node = True
            print("[serena] bridge abilitato ma node_id vuoto — nessun comando inviato "
                  "(imposta serena.node_id uguale al node_id di Serena)", flush=True)
        return False
    return True


def _camera_working(ip: str) -> bool:
    """Canonical confirmed-working predicate shared by BOTH the active-announcement
    path (_refresh_detection_ok) and the periodic fault driver, so the positive and
    negative sides can never disagree. A simulated camera is always working; otherwise
    working iff the stream is alive AND the tumble rule is confirmed enabled
    (rule_enabled is True — NOT 'unknown'/False). Reads per-camera state under _lock."""
    with _lock:
        cam = _cameras.get(ip)
        if not cam:
            return False
        if cam.get("simulated"):
            return True
        return bool(cam.get("stream_alive")) and cam.get("rule_enabled") is True


def _serena_trigger_topic() -> str:
    return f"{_cfg['serena_topic_prefix']}/{_cfg['serena_node_id']}/trigger/run"


def _serena_tts_topic() -> str:
    return f"{_cfg['serena_topic_prefix']}/{_cfg['serena_node_id']}/tts/set"


def _serena_log_target_once():
    """(A) Commissioning log — print the fully-resolved trigger/run topic exactly once
    when the bridge is enabled + configured, so the operator can confirm node_id."""
    global _serena_logged_target
    if _serena_logged_target:
        return
    if not _cfg.get("serena_enabled") or not _cfg.get("mqtt_host") or not _cfg.get("serena_node_id"):
        return
    _serena_logged_target = True
    print(f"[serena] bridge attivo — comando di caduta su '{_serena_trigger_topic()}' "
          f"(verifica che node_id combaci con quello di Serena)", flush=True)


def _mqtt_publish_serena_trigger(cam_name: str):
    """Publish one non-retained fall command to Serena's trigger/run topic. No-op when
    the client is None or the bridge is not enabled/configured. Never propagates."""
    if not _mqtt_client:
        return
    if not _serena_preconditions_ok():
        return
    try:
        topic  = _serena_trigger_topic()
        phrase = _cfg["serena_command_template"].format(cam_name=_serena_voice_name(cam_name))
        # (B) Emit-time connectivity check: log (don't skip) when disconnected — the
        # QoS-1 publish is buffered and will flush on reconnect.
        if not _mqtt_client.is_connected():
            print(f"[serena] ERRORE: broker non connesso, il comando di caduta potrebbe "
                  f"andare perso (topic {topic})", flush=True)
        info = _mqtt_client.publish(topic, payload=phrase, qos=1, retain=False)
        print(f"[serena] trigger → {topic} : {phrase!r}", flush=True)
        # Bounded (≤1s) broker-receipt confirmation — this runs on the per-camera read
        # thread, so it must not stall the loop. Confirms broker receipt, NOT Serena's.
        try:
            info.wait_for_publish(timeout=1)
        except Exception as e:
            print(f"[serena] ERRORE conferma publish trigger ({type(e).__name__}: {e})", flush=True)
        _mqtt_publish_serena_bridge_status()
    except Exception as e:
        print(f"[serena] trigger publish errore: {e}", flush=True)


def _serena_emit_tts(cam_name: str, template_key: str, kind: str):
    """Render `template_key` with the normalized cam name and publish to Serena's
    tts/set topic (non-retained, QoS 1). Caller has already checked the client,
    preconditions, connection, and the relevant feature gate."""
    try:
        text  = _cfg[template_key].format(cam_name=_serena_voice_name(cam_name))
        topic = _serena_tts_topic()
        _mqtt_client.publish(topic, payload=text, qos=1, retain=False)
        print(f"[serena] {kind} → {topic} : {text!r}", flush=True)
    except Exception as e:
        print(f"[serena] {kind} publish errore: {e}", flush=True)


def _mqtt_announce_serena_active(cam_name: str):
    """Startup 'sensore … attivo' announcement (gated on announce_ready)."""
    if not _mqtt_client or not _mqtt_client.is_connected():
        return
    if not _serena_preconditions_ok() or not _cfg.get("serena_announce_ready"):
        return
    _serena_emit_tts(cam_name, "serena_announce_template", "attivo")


def _mqtt_announce_serena_fault(cam_name: str):
    """'sensore … non attivo' fault announcement (gated on announce_fault)."""
    if not _mqtt_client or not _mqtt_client.is_connected():
        return
    if not _serena_preconditions_ok() or not _cfg.get("serena_announce_fault"):
        return
    _serena_emit_tts(cam_name, "serena_announce_fault_template", "guasto")


def _mqtt_announce_serena_recovery(cam_name: str):
    """Fault-recovery notice: speaks the ACTIVE template again, but gated on
    announce_fault (NOT announce_ready) — it is part of the fault-tracking feature,
    so it fires even when announce_ready is false. Do NOT route through
    _mqtt_announce_serena_active (which no-ops on announce_ready=false)."""
    if not _mqtt_client or not _mqtt_client.is_connected():
        return
    if not _serena_preconditions_ok() or not _cfg.get("serena_announce_fault"):
        return
    _serena_emit_tts(cam_name, "serena_announce_template", "recovery")


def _mqtt_publish_serena_bridge_status():
    """(D) Retained HA diagnostic entity reporting bridge health: enabled flag, live
    MQTT connection state, and the resolved target topic (attribute). No-op when the
    bridge is disabled. Reports ONVIF-side config/connectivity only — never claims
    Serena received a command."""
    global _serena_bridge_discovered
    if not _mqtt_client or not _cfg.get("serena_enabled"):
        return
    prefix = _cfg["mqtt_prefix"]
    uid    = "onvif_serena_bridge"
    base   = f"{prefix}/serena_bridge/status"
    node   = _cfg.get("serena_node_id", "")
    target = f"{_cfg['serena_topic_prefix']}/{node}/trigger/run"
    try:
        if not _serena_bridge_discovered:
            disc = {
                "name":                  "Serena bridge",
                "object_id":             "serena_bridge",
                "unique_id":             uid,
                "device_class":          "connectivity",
                "icon":                  "mdi:bridge",
                "state_topic":           base,
                "json_attributes_topic": f"{base}/attrs",
                "payload_on":            "on",
                "payload_off":           "off",
                "entity_category":       "diagnostic",
                "device": {
                    "identifiers":  [uid],
                    "name":         "ONVIF SUA — Serena bridge",
                    "model":        "Fall Detection",
                    "manufacturer": "Dahua ONVIF",
                },
            }
            _mqtt_client.publish(f"homeassistant/binary_sensor/{uid}/config",
                                 json.dumps(disc), qos=1, retain=True)
            _serena_bridge_discovered = True
        connected = bool(_mqtt_client.is_connected())
        attrs = {"enabled": bool(_cfg.get("serena_enabled")),
                 "target_topic": target, "node_id": node}
        _mqtt_client.publish(base, payload="on" if connected else "off", qos=1, retain=True)
        _mqtt_client.publish(f"{base}/attrs", json.dumps(attrs), qos=1, retain=True)
    except Exception as e:
        print(f"[serena] bridge status publish errore: {e}", flush=True)
