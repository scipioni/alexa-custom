"""Tasks 5.2 / 5.3 / 5.3a / 5.3b / 5.3c: the worker-side wiring — fall-start edge,
multi-camera independence, startup announcement via _refresh_detection_ok, the
multi-shot fault driver tick, and startup adoption of an in-progress fall."""
import time

from onvif_sua import config, mqtt, state, worker

from conftest import start_line, stop_line


def _triggers(cli):
    return [c for c in cli.calls if c[0].endswith("/trigger/run")]


def _tts(cli, needle=None):
    calls = [c for c in cli.calls if c[0].endswith("/tts/set")]
    return [c for c in calls if needle is None or needle in c[1]]


def _active_phrases(cli, name):
    return _tts(cli, f"terra {name} attivo")


def _fault_phrases(cli, name):
    return _tts(cli, f"terra {name} non attivo")


# ── 5.2: start-handler wiring ─────────────────────────────────────────────────────
def test_single_start_emits_once(fake_mqtt, run_cgi):
    run_cgi("10.0.0.1", "cucina", [start_line()])
    calls = _triggers(fake_mqtt)
    assert len(calls) == 1
    assert calls[0][1] == "caduta cucina"


def test_repeated_starts_while_active_emit_once(fake_mqtt, run_cgi):
    run_cgi("10.0.0.1", "cucina", [start_line(), start_line(), start_line()])
    assert len(_triggers(fake_mqtt)) == 1


def test_stop_then_start_re_arms(fake_mqtt, run_cgi, immediate_timer):
    run_cgi("10.0.0.1", "cucina", [start_line(), stop_line(), start_line()])
    assert len(_triggers(fake_mqtt)) == 2


# ── 5.3: multi-camera independence ────────────────────────────────────────────────
def test_two_cameras_each_emit_own_phrase(fake_mqtt, run_cgi):
    run_cgi("10.0.0.1", "cucina", [start_line()])
    run_cgi("10.0.0.2", "salotto", [start_line()])
    payloads = sorted(c[1] for c in _triggers(fake_mqtt))
    assert payloads == ["caduta cucina", "caduta salotto"]


def test_one_active_does_not_block_other(fake_mqtt, run_cgi):
    # cucina already fell (emits once); salotto then falls and still emits.
    run_cgi("10.0.0.1", "cucina", [start_line(), start_line()])   # 1 emit
    run_cgi("10.0.0.2", "salotto", [start_line()])                # 1 emit
    assert len(_triggers(fake_mqtt)) == 2


# ── 5.3a: startup announcement via _refresh_detection_ok ──────────────────────────
def _seed_static(ip, name):
    with state._lock:
        cam = worker._new_cam(ip, name)
        cam["_static"] = True
        state._cameras[ip] = cam
    return state._cameras[ip]


def _set(ip, **kw):
    with state._lock:
        state._cameras[ip].update(kw)


def test_announce_only_after_rule_confirmed(fake_mqtt):
    _seed_static("10.0.0.1", "cucina")
    # stream up, rule unknown → detection_ok may be 'on' but NO active announcement
    _set("10.0.0.1", stream_alive=True, rule_enabled="unknown")
    mqtt._refresh_detection_ok("10.0.0.1")
    assert _active_phrases(fake_mqtt, "cucina") == []
    # rule confirmed True → exactly one announcement
    _set("10.0.0.1", rule_enabled=True)
    mqtt._refresh_detection_ok("10.0.0.1")
    assert len(_active_phrases(fake_mqtt, "cucina")) == 1
    # re-announce guard: further refreshes / flaps do not re-announce
    mqtt._refresh_detection_ok("10.0.0.1")
    _set("10.0.0.1", stream_alive=False)
    mqtt._refresh_detection_ok("10.0.0.1")
    _set("10.0.0.1", stream_alive=True)
    mqtt._refresh_detection_ok("10.0.0.1")
    assert len(_active_phrases(fake_mqtt, "cucina")) == 1


def test_no_announce_when_rule_disabled(fake_mqtt):
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=True, rule_enabled=False)
    mqtt._refresh_detection_ok("10.0.0.1")
    assert _active_phrases(fake_mqtt, "cucina") == []


def test_no_announce_when_announce_ready_false(fake_mqtt):
    config._cfg["serena_announce_ready"] = False
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=True, rule_enabled=True)
    mqtt._refresh_detection_ok("10.0.0.1")
    assert _active_phrases(fake_mqtt, "cucina") == []


def test_two_cameras_each_announce_once(fake_mqtt):
    for ip, name in (("10.0.0.1", "cucina"), ("10.0.0.2", "salotto")):
        _seed_static(ip, name)
        _set(ip, stream_alive=True, rule_enabled=True)
        mqtt._refresh_detection_ok(ip)
    assert len(_active_phrases(fake_mqtt, "cucina")) == 1
    assert len(_active_phrases(fake_mqtt, "salotto")) == 1


# ── 5.3b: multi-shot fault driver ─────────────────────────────────────────────────
BASE = 1_000_000.0


def _configure_static(*cams):
    config._static_cameras = [{"ip": ip, "name": nm} for ip, nm in cams]


def test_fault_after_grace_then_repeats(fake_mqtt):
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")
    _configure_static(("10.0.0.1", "cucina"))

    worker._serena_fault_tick(BASE)                 # enter episode, no emit
    assert _fault_phrases(fake_mqtt, "cucina") == []
    worker._serena_fault_tick(BASE + 30)            # within grace (60)
    assert _fault_phrases(fake_mqtt, "cucina") == []
    worker._serena_fault_tick(BASE + 61)            # past grace → fault #1
    assert len(_fault_phrases(fake_mqtt, "cucina")) == 1
    worker._serena_fault_tick(BASE + 61 + 100)      # interval (300) not elapsed
    assert len(_fault_phrases(fake_mqtt, "cucina")) == 1
    worker._serena_fault_tick(BASE + 61 + 300)      # interval elapsed → fault #2
    assert len(_fault_phrases(fake_mqtt, "cucina")) == 2


def test_no_fault_within_grace_if_confirmed(fake_mqtt):
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")
    _configure_static(("10.0.0.1", "cucina"))
    worker._serena_fault_tick(BASE)                 # enter episode
    _set("10.0.0.1", stream_alive=True, rule_enabled=True)   # confirmed within grace
    worker._serena_fault_tick(BASE + 10)
    assert _fault_phrases(fake_mqtt, "cucina") == []


def test_fault_silent_when_disabled(fake_mqtt):
    config._cfg["serena_announce_fault"] = False
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")
    _configure_static(("10.0.0.1", "cucina"))
    worker._serena_fault_tick(BASE)
    worker._serena_fault_tick(BASE + 500)
    assert _fault_phrases(fake_mqtt, "cucina") == []


def test_recovery_emits_active_once_and_rearms(fake_mqtt):
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")
    _configure_static(("10.0.0.1", "cucina"))
    worker._serena_fault_tick(BASE)
    worker._serena_fault_tick(BASE + 61)            # fault #1
    assert len(_fault_phrases(fake_mqtt, "cucina")) == 1
    # recover → one active announcement, episode reset
    _set("10.0.0.1", stream_alive=True, rule_enabled=True)
    worker._serena_fault_tick(BASE + 200)
    assert len(_active_phrases(fake_mqtt, "cucina")) == 1
    # re-arm: degrade again → fault after grace
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")
    worker._serena_fault_tick(BASE + 300)           # enter new episode
    worker._serena_fault_tick(BASE + 300 + 61)      # past grace → fault again
    assert len(_fault_phrases(fake_mqtt, "cucina")) == 2


def test_recovery_fires_when_announce_ready_false(fake_mqtt):
    # RH2: announce_ready false + announce_fault true → recovery still speaks 'attivo'
    config._cfg["serena_announce_ready"] = False
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")
    _configure_static(("10.0.0.1", "cucina"))
    worker._serena_fault_tick(BASE)
    worker._serena_fault_tick(BASE + 61)            # fault #1
    _set("10.0.0.1", stream_alive=True, rule_enabled=True)
    worker._serena_fault_tick(BASE + 200)           # recovery
    assert len(_active_phrases(fake_mqtt, "cucina")) == 1


def test_no_double_attivo_recovery_then_refresh(fake_mqtt):
    # RM1: after recovery sets serena_announced, the D6 first-confirm path does NOT
    # also announce → exactly one active announcement across the transition.
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")
    _configure_static(("10.0.0.1", "cucina"))
    worker._serena_fault_tick(BASE)
    worker._serena_fault_tick(BASE + 61)            # fault #1
    _set("10.0.0.1", stream_alive=True, rule_enabled=True)
    worker._serena_fault_tick(BASE + 200)           # recovery → active #1 + serena_announced=True
    mqtt._refresh_detection_ok("10.0.0.1")          # D6 path must be suppressed
    assert len(_active_phrases(fake_mqtt, "cucina")) == 1


def test_simulated_camera_never_faults(fake_mqtt):
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.1", "cucina")
    _set("10.0.0.1", simulated=True, stream_alive=False, rule_enabled="unknown")
    _configure_static(("10.0.0.1", "cucina"))
    worker._serena_fault_tick(BASE)
    worker._serena_fault_tick(BASE + 500)
    assert _fault_phrases(fake_mqtt, "cucina") == []


def test_fault_two_cameras_independent(fake_mqtt):
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.1", "cucina")
    _seed_static("10.0.0.2", "salotto")
    _set("10.0.0.1", stream_alive=False, rule_enabled="unknown")   # faulting
    _set("10.0.0.2", stream_alive=True, rule_enabled=True)         # healthy
    _configure_static(("10.0.0.1", "cucina"), ("10.0.0.2", "salotto"))
    worker._serena_fault_tick(BASE)
    worker._serena_fault_tick(BASE + 61)
    assert len(_fault_phrases(fake_mqtt, "cucina")) == 1
    assert _fault_phrases(fake_mqtt, "salotto") == []


def test_never_connected_camera_faults(fake_mqtt):
    # driver iterates configured cameras — a never-connected one still has an entry
    # (created by the worker) and must fault after grace.
    config._cfg["serena_announce_fault"] = True
    _seed_static("10.0.0.9", "ingresso")   # stream_alive False, rule 'unknown' by default
    _configure_static(("10.0.0.9", "ingresso"))
    worker._serena_fault_tick(BASE)
    worker._serena_fault_tick(BASE + 61)
    assert len(_fault_phrases(fake_mqtt, "ingresso")) == 1


# ── 5.3c: startup adoption of an in-progress fall ─────────────────────────────────
def test_adopt_recent_in_progress_fall(fake_mqtt, run_cgi):
    with state._lock:
        state._cam_alarms["cucina"] = "on"
    worker._alarm_saved_at = time.time()
    # No stream events; connect+republish triggers adoption. A trailing start must NOT
    # double-emit (episode adopted → alarm_active True).
    run_cgi("10.0.0.1", "cucina", [start_line()])
    assert len(_triggers(fake_mqtt)) == 1


def test_stale_in_progress_fall_not_adopted(fake_mqtt, run_cgi):
    with state._lock:
        state._cam_alarms["cucina"] = "on"
    worker._alarm_saved_at = time.time() - 10_000   # older than max_age (300)
    run_cgi("10.0.0.1", "cucina", [])
    assert _triggers(fake_mqtt) == []


def test_no_alarm_no_adoption(fake_mqtt, run_cgi):
    worker._alarm_saved_at = time.time()
    run_cgi("10.0.0.1", "cucina", [])    # _cam_alarms has no 'on' entry
    assert _triggers(fake_mqtt) == []


def test_adopt_then_stop_then_start_re_arms(fake_mqtt, run_cgi, immediate_timer):
    with state._lock:
        state._cam_alarms["cucina"] = "on"
    worker._alarm_saved_at = time.time()
    # adopt (emit 1) → stop (fires _fire_stop immediately) → start (emit 2)
    run_cgi("10.0.0.1", "cucina", [stop_line(), start_line()])
    assert len(_triggers(fake_mqtt)) == 2
