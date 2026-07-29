"""Tasks 5.1 / 5.1b / 5.4: the mqtt emit helpers, _camera_working, and observability."""
from onvif_sua import config, mqtt, state

from conftest import FakeMqtt


def _trigger_calls(cli):
    return cli.topics("/trigger/run")


def _tts_calls(cli):
    return cli.topics("/tts/set")


# ── 5.1: _mqtt_publish_serena_trigger ─────────────────────────────────────────────
def test_trigger_emits_when_enabled(fake_mqtt):
    mqtt._mqtt_publish_serena_trigger("cucina")
    calls = _trigger_calls(fake_mqtt)
    assert len(calls) == 1
    topic, payload, qos, retain = calls[0]
    assert topic == "alexa/serena/trigger/run"
    assert payload == "caduta_cucina"
    assert qos == 1 and retain is False


def test_trigger_renders_normalized_name(fake_mqtt):
    mqtt._mqtt_publish_serena_trigger("Salotto-1")
    assert _trigger_calls(fake_mqtt)[0][1] == "caduta_salotto_1"


def test_trigger_noop_when_disabled(fake_mqtt):
    config._cfg["serena_enabled"] = False
    mqtt._mqtt_publish_serena_trigger("cucina")
    assert _trigger_calls(fake_mqtt) == []


def test_trigger_noop_when_node_id_empty(fake_mqtt, capsys):
    config._cfg["serena_node_id"] = ""
    mqtt._mqtt_publish_serena_trigger("cucina")
    assert _trigger_calls(fake_mqtt) == []
    assert "node_id vuoto" in capsys.readouterr().out


def test_trigger_noop_when_mqtt_host_empty(fake_mqtt):
    config._cfg["mqtt_host"] = ""
    mqtt._mqtt_publish_serena_trigger("cucina")
    assert _trigger_calls(fake_mqtt) == []


def test_trigger_noop_when_client_none(serena_cfg):
    mqtt._mqtt_client = None
    mqtt._mqtt_publish_serena_trigger("cucina")   # must not raise


def test_trigger_swallows_publish_exception(fake_mqtt):
    def _boom(*a, **k):
        raise RuntimeError("broker down")

    fake_mqtt.publish = _boom
    # Must not propagate — the caller's state publish must be unaffected.
    mqtt._mqtt_publish_serena_trigger("cucina")


def test_trigger_swallows_template_exception(fake_mqtt):
    config._cfg["serena_command_template"] = "caduta_{cam_name} {oops}"  # bad at render
    mqtt._mqtt_publish_serena_trigger("cucina")   # must not raise
    assert _trigger_calls(fake_mqtt) == []


# ── 5.4: observability (B/D) ──────────────────────────────────────────────────────
def test_trigger_logs_error_when_disconnected(serena_cfg, capsys):
    cli = FakeMqtt(connected=False)
    mqtt._mqtt_client = cli
    mqtt._mqtt_publish_serena_trigger("cucina")
    out = capsys.readouterr().out
    assert "broker non connesso" in out
    # still attempts the (buffered) publish
    assert len(_trigger_calls(cli)) == 1


def test_log_target_once(serena_cfg, capsys):
    mqtt._serena_logged_target = False
    mqtt._serena_log_target_once()
    mqtt._serena_log_target_once()
    out = capsys.readouterr().out
    assert out.count("alexa/serena/trigger/run") == 1


def test_bridge_status_reflects_connection(fake_mqtt):
    mqtt._serena_bridge_discovered = False
    mqtt._mqtt_publish_serena_bridge_status()
    state_calls = fake_mqtt.topics("serena_bridge/status")
    # discovery + state + attrs published; find the state topic exactly
    st = [c for c in fake_mqtt.calls if c[0] == "onvif/serena_bridge/status"]
    attrs = [c for c in fake_mqtt.calls if c[0] == "onvif/serena_bridge/status/attrs"]
    assert st and st[0][1] == "on" and st[0][3] is True   # retained
    assert attrs and "alexa/serena/trigger/run" in attrs[0][1]
    assert state_calls


def test_bridge_status_noop_when_disabled(fake_mqtt):
    config._cfg["serena_enabled"] = False
    mqtt._serena_bridge_discovered = False
    mqtt._mqtt_publish_serena_bridge_status()
    assert fake_mqtt.topics("serena_bridge/status") == []


# ── 5.1b: announcements ───────────────────────────────────────────────────────────
def test_announce_active_emits(fake_mqtt):
    mqtt._mqtt_announce_serena_active("cucina")
    calls = _tts_calls(fake_mqtt)
    assert len(calls) == 1
    topic, payload, qos, retain = calls[0]
    assert topic == "alexa/serena/tts/set"
    assert payload == "sensore uomo a terra cucina attivo"
    assert qos == 1 and retain is False


def test_announce_active_noop_when_announce_ready_false(fake_mqtt):
    config._cfg["serena_announce_ready"] = False
    mqtt._mqtt_announce_serena_active("cucina")
    assert _tts_calls(fake_mqtt) == []


def test_announce_active_noop_when_disconnected(serena_cfg):
    mqtt._mqtt_client = FakeMqtt(connected=False)
    mqtt._mqtt_announce_serena_active("cucina")
    assert _tts_calls(mqtt._mqtt_client) == []


def test_announce_active_noop_when_node_empty(fake_mqtt):
    config._cfg["serena_node_id"] = ""
    mqtt._mqtt_announce_serena_active("cucina")
    assert _tts_calls(fake_mqtt) == []


def test_announce_active_swallows_exception(fake_mqtt):
    config._cfg["serena_announce_template"] = "attivo {cam_name} {oops}"
    mqtt._mqtt_announce_serena_active("cucina")   # must not raise
    assert _tts_calls(fake_mqtt) == []


def test_announce_fault_gated(fake_mqtt):
    # off by default → no-op
    mqtt._mqtt_announce_serena_fault("cucina")
    assert _tts_calls(fake_mqtt) == []
    config._cfg["serena_announce_fault"] = True
    mqtt._mqtt_announce_serena_fault("cucina")
    assert _tts_calls(fake_mqtt)[0][1] == "attenzione, sensore uomo a terra cucina non attivo"


def test_recovery_gated_on_announce_fault_not_ready(fake_mqtt):
    # announce_ready false + announce_fault true → recovery STILL fires (active phrase)
    config._cfg["serena_announce_ready"] = False
    config._cfg["serena_announce_fault"] = True
    mqtt._mqtt_announce_serena_recovery("cucina")
    calls = _tts_calls(fake_mqtt)
    assert len(calls) == 1
    assert calls[0][1] == "sensore uomo a terra cucina attivo"


def test_recovery_noop_when_announce_fault_false(fake_mqtt):
    config._cfg["serena_announce_fault"] = False
    mqtt._mqtt_announce_serena_recovery("cucina")
    assert _tts_calls(fake_mqtt) == []


# ── 5.1b: _camera_working ─────────────────────────────────────────────────────────
def _seed_cam(ip, **kw):
    with state._lock:
        cam = {"simulated": False, "stream_alive": False, "rule_enabled": "unknown"}
        cam.update(kw)
        state._cameras[ip] = cam


def test_camera_working_simulated_always(serena_cfg):
    _seed_cam("1.1.1.1", simulated=True, stream_alive=False, rule_enabled="unknown")
    assert mqtt._camera_working("1.1.1.1") is True


def test_camera_working_stream_and_rule(serena_cfg):
    _seed_cam("1.1.1.2", stream_alive=True, rule_enabled=True)
    assert mqtt._camera_working("1.1.1.2") is True


def test_camera_working_false_states(serena_cfg):
    _seed_cam("1.1.1.3", stream_alive=True, rule_enabled="unknown")
    assert mqtt._camera_working("1.1.1.3") is False
    _seed_cam("1.1.1.4", stream_alive=True, rule_enabled=False)
    assert mqtt._camera_working("1.1.1.4") is False
    _seed_cam("1.1.1.5", stream_alive=False, rule_enabled=True)
    assert mqtt._camera_working("1.1.1.5") is False
    assert mqtt._camera_working("nope") is False
