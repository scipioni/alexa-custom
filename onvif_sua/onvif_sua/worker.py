"""Runtime engine: per-camera ONVIF worker, Dahua attach-stream + keepalive threads,
periodic rule-check, alarm/event recording, camera lifecycle (add/remove/promote),
persistence + keepalive/republish loops, and the asyncio main loop."""
import asyncio
import json
import os
import threading
import time
from datetime import datetime
from typing import Optional

from . import config
from . import state as _state
from . import mqtt
from .config import (
    _cfg, SETTINGS_FILE, RESULTS_FILE, ALARM_FILE,
    RETRY_SLEEP, RENEW_EVERY, PULL_NS,
    MAX_LOG_GLOBAL, MAX_LOG_CAM, FALL_TOPICS, ALARM_KEEPALIVE,
    SCAN_SUBNET, _load_static_cameras,
)
from .state import (
    _lock, _cameras, _event_log, _alarms, _cam_alarms, _removed_ips,
    _worker_tasks, _rule_tasks, _active_pullpoints, _cgi_started,
    _cgi_stop_events, _cgi_threads, _keepalive_threads, _cgi_responses,
    _Backoff, _auth_gate,
    _mark_auth_failed, _is_auth_failed, _clear_auth_failed,
)
from .mqtt import (
    _mqtt_publish, _mqtt_publish_detection_ok,
    _compute_detection_ok, _refresh_detection_ok,
    _mqtt_publish_serena_trigger, _camera_working,
    _mqtt_announce_serena_fault, _mqtt_announce_serena_recovery,
)
from .connect import (
    _try_connect, _SubLimitError, _AuthError, _namespaces_to_labels,
    _safe_close, _safe_unsubscribe, _get_analytics_rules,
)


def _new_cam(ip: str, name: str = "", user: str = "", pwd: str = "", port: int = 80) -> dict:
    return {
        "ip":            ip,
        "port":          port,
        "name":          name or ip,
        "status":        "connecting",
        "user":          user,
        "pass":          pwd,
        "creds_tried":   [],
        "services":      [],
        "analytics_rules": {},
        "topics":        {},
        "event_count":   0,
        "error":         "",
        "connect_ts":    None,
        "last_event_ts": None,
        "sub_addr":      "",
        "name_verified": True,
        # ── detection-liveness state (guarded by _lock) ──
        "last_seen":     0.0,        # ts of last heartbeat/event (or keepalive probe)
        "stream_alive":  False,      # attach-stream liveness
        "rule_enabled":  "unknown",  # True | False | "unknown"
        "detection_ok":  None,       # "on" | "off" (last published)
        # ── Serena bridge per-camera state (guarded by _lock) ──
        "serena_announced":     False,  # first confirmed-working announcement sent this run
        "serena_fault_since":   None,   # float ts entering current not-working episode | None
        "serena_fault_last_ts": 0.0,    # last fault-announcement emit (interval gate)
        "serena_fault_announced": False,# ≥1 fault emitted this episode (drives recovery notice)
        # ── test/simulation overlay (ephemeral, never persisted) ──
        "simulated":     False,      # True → fake connected+fall, real worker suppressed
    }
def _set_status_locked(cam: dict, value: str):
    """Assign cam['status'] UNLESS the camera is in simulation mode — while a row is
    being simulated the toggle owns the status and the real worker must not clobber it
    (otherwise an absent camera would flip back to no_onvif within seconds). Caller
    MUST already hold _lock."""
    if not cam.get("simulated"):
        cam["status"] = value
def _start_cgi_stream(ip: str, port: int, user: str, pwd: str, name: str):
    """Start the Dahua attach-stream thread for an IP exactly once (per-IP stop
    event tracked for clean teardown). Independent of ONVIF (task 3.5)."""
    with _lock:
        if ip in _cgi_started:
            return
        _cgi_started.add(ip)
        ev = threading.Event()
        _cgi_stop_events[ip] = ev
    t = threading.Thread(
        target=_dahua_cgi_thread,
        args=(ip, port, user, pwd, name, ev),
        daemon=True,
        name=f"cgi-{ip}",
    )
    _cgi_threads[ip] = t
    t.start()
    # Fallback (keepalive) mode: an authenticated probe drives liveness because
    # the attach stream carries no periodic traffic (task 4.6).
    if config.LIVENESS_MODE == "keepalive":
        kt = threading.Thread(
            target=_keepalive_probe_thread,
            args=(ip, port, user, pwd, name, ev),
            daemon=True,
            name=f"keepalive-{ip}",
        )
        _keepalive_threads[ip] = kt
        kt.start()
async def _camera_worker(info: dict):
    ip     = info["ip"]
    name   = info.get("name", "") or ip
    user   = info.get("user", "admin")
    pwd    = info.get("pass", "")
    port   = info.get("port", 80)
    static = bool(info.get("static", False))

    with _lock:
        if ip in _cameras:
            return   # già gestita
        _cameras[ip] = _new_cam(ip, name, user, pwd, port)
        _cameras[ip]["_static"] = static

    # Liveness (attach stream + rule check) runs INDEPENDENTLY of the ONVIF
    # connection (task 3.5 / spec "Liveness stream runs independently of ONVIF").
    _start_cgi_stream(ip, port, user, pwd, name)
    if static:
        _ensure_rule_task(ip, port, user, pwd)

    # Single common credential — no fallback list, no port probing (task 3.3).
    onvif_backoff = _Backoff()

    while True:
        if ip in _removed_ips:
            print(f"[onvif] {ip} ({name}) — rimossa, worker terminato", flush=True)
            return

        # Auth quarantine: a login already failed for this camera (here or on another
        # path — CGI/keepalive/rule). Stop retrying so a wrong-but-real password never
        # trips the Dahua anti-intrusion lockout; the warning is shown in UI + log.
        if _is_auth_failed(ip):
            with _lock:
                _set_status_locked(_cameras[ip], "auth_failed")
            print(f"[onvif] {ip} ({name}) — worker sospeso (login fallito): correggi la "
                  f"password in .env e riavvia", flush=True)
            return

        # Startup auth gate (task 3.10) staggers the first attempt across paths.
        await _auth_gate.wait_async(ip)

        conn           = None
        sub_limit_info = None
        auth_err       = None
        with _lock:
            _set_status_locked(_cameras[ip], "connecting")
            _cameras[ip]["creds_tried"] = [f"{user}/{'*'*len(pwd)}"]
        try:
            conn = await asyncio.wait_for(_try_connect(ip, port, user, pwd), timeout=12)
        except _AuthError:
            auth_err = True
        except _SubLimitError as sle:
            sub_limit_info = sle
        except (asyncio.TimeoutError, Exception):
            conn = None

        if auth_err:
            # Hard auth failure (credentials rejected). Quarantine and STOP — do not
            # back off and retry, which would eventually lock out the camera.
            detail = f"Login ONVIF fallito (credenziali rifiutate) — user='{user}'"
            first = _mark_auth_failed(ip, "ONVIF", detail, name)
            if first:
                print(f"[onvif] {ip} ({name}) — ⛔ LOGIN FALLITO: credenziali ONVIF rifiutate. "
                      f"Sospendo ogni tentativo per NON far scattare il blocco anti-intrusione "
                      f"della telecamera. Correggi CAMERA_PASSWORD in .env e riavvia.", flush=True)
            with _lock:
                _set_status_locked(_cameras[ip], "auth_failed")
                _cameras[ip]["error"] = detail
            return

        if sub_limit_info and not conn:
            # Auth succeeded (credential correct) but PullPoint subscription is
            # occupied by another client — liveness stream keeps running regardless.
            _auth_gate.mark_success(ip)
            onvif_backoff.reset()
            u, p = sub_limit_info.creds
            short_svcs = _namespaces_to_labels(sub_limit_info.namespaces)
            with _lock:
                _set_status_locked(_cameras[ip], "sub_limit")
                _cameras[ip]["user"]     = u
                _cameras[ip]["services"] = short_svcs
                _cameras[ip]["error"]    = "Subscription occupata (altro client ONVIF attivo)"
            print(f"[onvif] {ip} ({name}) — auth OK ma subscription occupata", flush=True)
            await asyncio.sleep(RETRY_SLEEP * 20)
            continue

        if not conn:
            # Capped exponential backoff on the ONVIF auth path (task 3.7). The
            # distinct "check the common credential" hint is logged on the FIRST
            # failure (before backing off) so a wrong fleet password is diagnosed
            # at boot; subsequent retries log tersely.
            first_fail = onvif_backoff.is_fresh()
            delay = onvif_backoff.next_delay()
            with _lock:
                _set_status_locked(_cameras[ip], "no_onvif")
                _cameras[ip]["error"]  = "ONVIF non connesso (verificare la credenziale comune)"
            if first_fail:
                print(f"[onvif] {ip} ({name}) — CONNESSIONE ONVIF FALLITA: verificare la "
                      f"CREDENZIALE COMUNE (user='{user}', porta={port}) in settings.yaml — "
                      f"backoff {delay:.0f}s", flush=True)
            else:
                print(f"[onvif] {ip} ({name}) — ONVIF non connesso, nuovo tentativo tra {delay:.0f}s", flush=True)
            await asyncio.sleep(delay)
            continue

        # Connected.
        _auth_gate.mark_success(ip)
        onvif_backoff.reset()
        used_creds = (user, pwd)
        cam_obj, evt_svc, pullpoint, namespaces = conn
        short_svcs = _namespaces_to_labels(namespaces)
        with _lock:
            already_queried = _cameras[ip].get("_analytics_queried", False)
            _set_status_locked(_cameras[ip], "connected")
            _cameras[ip].update({
                "user":       used_creds[0],
                "pass":       used_creds[1],
                "connect_ts": datetime.now().isoformat(timespec="seconds"),
                "services":   short_svcs,
                "error":      "",
                "sub_addr":   cam_obj.xaddrs.get(PULL_NS, ""),
            })
        _active_pullpoints[ip] = pullpoint   # track for clean Unsubscribe on drop/shutdown
        print(f"[onvif] {ip} ({name}) — connesso [{used_creds[0]}] [{', '.join(short_svcs)}]", flush=True)

        if not already_queried:
            rules = await _get_analytics_rules(cam_obj, ip)
            with _lock:
                _cameras[ip]["analytics_rules"]    = rules
                _cameras[ip]["_analytics_queried"] = True

        last_renew    = time.time()
        try:
            while True:
                if ip in _removed_ips:
                    return

                with _lock:
                    cam = _cameras.get(ip)
                    if cam is None:
                        return   # camera removed underneath us
                    name = cam.get("name", name)

                if time.time() - last_renew >= RENEW_EVERY:
                    try:
                        # Renew va sul pullpoint (subscription ref), non sull'events service
                        await pullpoint.Renew({"TerminationTime": "PT2M"})
                        last_renew = time.time()
                    except Exception:
                        pass

                resp = await asyncio.wait_for(
                    pullpoint.PullMessages({"Timeout": "PT10S", "MessageLimit": 100}),
                    timeout=20
                )

                # The PullMessages long-poll may return just after a removal — don't
                # process (or log) events for a camera that is being torn down.
                if ip in _removed_ips:
                    return

                for msg in (resp.NotificationMessage or []):
                    topic = str(getattr(getattr(msg, "Topic", None), "_value_1", "") or "")
                    try:
                        items = msg.Message._value_1.Data.SimpleItem
                        if not isinstance(items, list):
                            items = [items]
                        data = {i.Name: i.Value for i in items}
                    except Exception:
                        data = {}
                    print(f"[EVENT] {ip} | {topic} | {data}", flush=True)
                    _record_event(ip, name, topic, data)
                    _check_fall_alarm(ip, topic, data)

        except Exception as e:
            with _lock:
                c = _cameras.get(ip)
                if c is not None:
                    c["status"] = "error"
                    c["error"]  = str(e)[:120]
            print(f"[onvif] {ip} ({name}) — disconnesso: {e}", flush=True)
        finally:
            # Free the camera's PullPoint subscription slot BEFORE closing the session,
            # so on reconnect/restart the Dahua immediately accepts a fresh subscription
            # instead of us waiting out the stale one (root cause of long 'connessione…').
            _active_pullpoints.pop(ip, None)
            await _safe_unsubscribe(pullpoint)
            # Always close the ONVIF session — on removal AND before every reconnect
            # — so aiohttp doesn't log "Unclosed client session".
            await _safe_close(cam_obj)

        if ip in _removed_ips:
            return
        await asyncio.sleep(RETRY_SLEEP)
# Epoch of alarm.json's `saved_at` at load — the recency reference for adopting an
# in-progress fall at startup (task 3.5). 0.0 when absent/unparseable.
_alarm_saved_at: float = 0.0


def _load_alarm_file():
    """Carica alarm.json in _cam_alarms e _alarms all'avvio per persistere lo stato."""
    global _alarm_saved_at
    try:
        with open(ALARM_FILE) as f:
            data = json.load(f)
        # Preserve saved_at (as epoch) BEFORE popping it — used by the startup
        # in-progress-fall adoption recency gate.
        saved_at_raw = data.pop("saved_at", None)
        try:
            _alarm_saved_at = datetime.fromisoformat(saved_at_raw).timestamp() if saved_at_raw else 0.0
        except (ValueError, TypeError):
            _alarm_saved_at = 0.0
        # Prune persisted entries for cameras that are no longer configured. A camera
        # renamed or removed by hand-editing settings.yaml (bypassing the rename API,
        # which migrates the alarm key) would otherwise leave an orphaned "on" that no
        # worker can ever clear — latching the global "Alarm uomo a terra" ON forever.
        # Only prune when the configured set is non-empty, so a transient config-parse
        # hiccup (empty set) can't nuke a legitimate in-progress alarm.
        configured = config._configured_camera_names()
        loaded = 0
        with _lock:
            for cam_name, state in data.items():
                if configured and cam_name not in configured:
                    print(f"[alarm] ignoro stato persistito per '{cam_name}' "
                          f"(telecamera non più configurata)", flush=True)
                    continue
                _cam_alarms[cam_name] = state
                loaded += 1
            if _cam_alarms:
                any_on = any(v == "on" for v in _cam_alarms.values())
                _alarms["Alarm uomo a terra"] = "on" if any_on else "off"
        print(f"[alarm] caricato {loaded}/{len(data)} voci da {ALARM_FILE}", flush=True)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[alarm] errore lettura {ALARM_FILE}: {e}", flush=True)
def _write_alarm_file():
    """Scrive /data/alarm.json atomicamente con lo stato corrente degli allarmi per cam."""
    try:
        os.makedirs(os.path.dirname(ALARM_FILE), exist_ok=True)
        with _lock:
            data = {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                **_cam_alarms,
            }
        tmp = ALARM_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, ALARM_FILE)
    except Exception as e:
        print(f"[alarm-file] errore scrittura: {e}", flush=True)
def _is_heartbeat_line(line: str) -> bool:
    """Recognize a heartbeat in whichever form the firmware emits it — a
    `Code=Heartbeat` record or a bare `Heartbeat` line / boundary marker.
    (Exact on-wire form confirmed by pre-flight task 1.1.)"""
    lc = line.lower()
    return "heartbeat" in lc
def _mark_stream_seen(ip: str, alive: bool = True):
    """Advance last_seen and (re)assert stream-liveness from the attach thread.
    Publishes detection_ok outside the lock only when it actually changed."""
    with _lock:
        cam = _cameras.get(ip)
        if cam is None:
            return
        if cam.get("simulated"):
            return   # simulation owns stream_alive/liveness; don't let the real stream clobber it
        if alive:
            cam["last_seen"] = time.time()
        changed = cam.get("stream_alive") != alive
        cam["stream_alive"] = alive
    if changed:
        _refresh_detection_ok(ip)
def _dahua_cgi_thread(ip: str, port: int, user: str, pwd: str, name: str,
                      stop_event: threading.Event):
    """Thread: Dahua attach stream — carries TumbleDetection (fall) events AND,
    in heartbeat mode, periodic Heartbeat messages used for stream-liveness.

    Alarm debounce: primo Start → ON immediato; Stop avvia timer 10s;
    se nessun Start entro 10s → OFF. Start durante timer → annulla timer.

    Liveness (heartbeat mode): the FINITE read timeout of gap_factor × N is the
    single gap-detection mechanism (task 4.3/4.4). Any heartbeat/event resets the
    read deadline; total silence for gap_factor × N raises ReadTimeout → not-alive,
    close, reconnect. In keepalive (fallback) mode the read timeout only recovers a
    dead socket and does NOT drive not-alive (the keepalive probe owns liveness).
    """
    import requests
    import urllib3
    from requests.auth import HTTPDigestAuth

    heartbeat_mode = (config.LIVENESS_MODE != "keepalive")
    if heartbeat_mode:
        url = (f"http://{ip}:{port}/cgi-bin/eventManager.cgi"
               f"?action=attach&codes=[All]&heartbeat={config.HEARTBEAT_INTERVAL}")
        read_timeout = config.HEARTBEAT_GAP_FACTOR * config.HEARTBEAT_INTERVAL
    else:
        url = f"http://{ip}:{port}/cgi-bin/eventManager.cgi?action=attach&codes=[All]"
        read_timeout = config.KEEPALIVE_INTERVAL + 10  # margin
    auth = HTTPDigestAuth(user, pwd)

    TUMBLE_CODE  = "TumbleDetection"
    STOP_DELAY   = 10.0   # secondi di silenzio prima di segnare OFF
    NOISY        = {"IntelliFrame", "NewFile", "TimeChange", "NTPStatusUpdate",
                    "VideoLoss", "VideoDetectMotion", "VideoBlind",
                    "VideoMotionInfo", "KeepAlive"}

    alarm_active = False
    stop_timer: Optional[threading.Timer] = None
    backoff = _Backoff()
    first_attach = True
    # Distinct from first_attach (which the auth-gate consumes BEFORE the connect):
    # this fires the startup in-progress-fall adoption once, on the first SUCCESSFUL
    # connect + state republish (task 3.5).
    serena_startup_pending = True

    def _current_name() -> str:
        with _lock:
            return _cameras.get(ip, {}).get("name", name)

    def _fire_stop():
        nonlocal alarm_active, stop_timer
        alarm_active = False
        stop_timer   = None
        cur = _current_name()
        with _lock:
            _alarms["Alarm uomo a terra"] = "off"
            _cam_alarms[cur] = "off"
        print(f"[ALARM-CGI] {ip} ({cur}) TumbleDetection quieto {STOP_DELAY:.0f}s → alarm=off", flush=True)
        _record_event(ip, cur, "Dahua/TumbleDetection", {"alarm": "off"})
        _write_alarm_file()
        _mqtt_publish(cur, "off")

    def _cancel_timer():
        nonlocal stop_timer
        if stop_timer:
            stop_timer.cancel()
            stop_timer = None

    while not stop_event.is_set():
        # Auth quarantine (set here on 401/403, or by another path): stop the attach
        # thread so a rejected credential is never retried into the lockout.
        if _is_auth_failed(ip):
            break
        # Startup auth gate (task 3.10) on the very first attach for this camera.
        if first_attach:
            _auth_gate.wait_sync(ip)
            first_attach = False
        resp = None
        try:
            resp = requests.get(url, auth=auth, stream=True, timeout=(10, read_timeout))
            _cgi_responses[ip] = resp

            if resp.status_code in (401, 403):
                # Hard common-credential auth failure. Quarantine and STOP the attach
                # thread — do NOT back off and retry, which would eventually trip the
                # Dahua anti-intrusion lockout ("blocking the camera forever").
                detail = f"Login CGI fallito (HTTP {resp.status_code}) — user='{user}'"
                first = _mark_auth_failed(ip, "Dahua CGI", detail, _current_name())
                if first:
                    print(f"[dahua-cgi] {ip} ⛔ LOGIN FALLITO HTTP {resp.status_code}: sospendo "
                          f"lo stream per NON far scattare il blocco anti-intrusione della "
                          f"telecamera. Correggi CAMERA_PASSWORD in .env e riavvia.", flush=True)
                if heartbeat_mode:
                    _mark_stream_seen(ip, alive=False)
                break
            if resp.status_code != 200:
                print(f"[dahua-cgi] {ip} HTTP {resp.status_code} — riprovo in 60s", flush=True)
                stop_event.wait(60)
                continue

            _auth_gate.mark_success(ip)
            backoff.reset()
            print(f"[dahua-cgi] {ip} ({_current_name()}) stream connesso "
                  f"(mode={'heartbeat' if heartbeat_mode else 'keepalive'}, read_timeout={read_timeout:.0f}s)", flush=True)
            # Successful (re)connect restores stream-liveness in heartbeat mode.
            if heartbeat_mode:
                _mark_stream_seen(ip, alive=True)
            # Announce the fall sensor (discovery + current state) as soon as the
            # stream connects, so it appears in HA together with detection_ok
            # instead of waiting for the first alarm event / keepalive tick.
            cur = _current_name()
            _mqtt_publish(cur, _cam_alarms.get(cur, "off"))

            # Serena bridge: adopt an in-progress fall that began before this process
            # started (the action=start edge won't re-fire for it). Only on the first
            # successful connect, only if a fall isn't already adopted here, the
            # persisted state is "on", and it was saved recently enough. Setting
            # alarm_active=True adopts the episode so action=start won't double-emit and
            # a later _fire_stop re-arms. Fault-isolated (helper never raises).
            if serena_startup_pending:
                serena_startup_pending = False
                if (not alarm_active and _cam_alarms.get(cur) == "on"
                        and (time.time() - _alarm_saved_at)
                        <= _cfg["serena_startup_alarm_max_age_s"]):
                    alarm_active = True
                    print(f"[serena] {ip} ({cur}) — caduta in corso adottata all'avvio "
                          f"→ invio comando", flush=True)
                    _mqtt_publish_serena_trigger(cur)

            # Read line-by-line from the RAW socket stream — NOT resp.iter_lines():
            # iter_lines() buffers a 512-byte chunk before yielding, so small 9-byte
            # `Heartbeat` messages are delivered in a delayed batch (~read_timeout
            # later), which defeats the gap watchdog. resp.raw.readline() delivers
            # each line as it arrives and honors the finite socket read timeout.
            while not stop_event.is_set():
                raw = resp.raw.readline()
                if not raw:
                    break   # stream closed cleanly by the server
                line = raw.decode("utf-8", errors="replace").strip() if isinstance(raw, bytes) else raw.strip()
                if not line:
                    continue

                # Heartbeat OR event advances last_seen (never only on fall events).
                if _is_heartbeat_line(line):
                    if heartbeat_mode:
                        _mark_stream_seen(ip, alive=True)
                    continue
                if not line.startswith("Code="):
                    continue
                if heartbeat_mode:
                    _mark_stream_seen(ip, alive=True)

                main  = line.split(";data=")[0]
                parts = {}
                for seg in main.split(";"):
                    if "=" in seg:
                        k, _, v = seg.partition("=")
                        parts[k.strip()] = v.strip()

                code   = parts.get("Code", "")
                action = parts.get("action", "").lower()

                # Capture the (possibly multi-line) data={...} JSON that follows the
                # Code line. Dahua wraps it in the multipart body, so accumulate
                # continuation lines until the JSON braces balance.
                data_obj = {}
                if ";data=" in line:
                    data_str = line.split(";data=", 1)[1]
                    depth = data_str.count("{") - data_str.count("}")
                    guard = 0
                    while depth > 0 and guard < 500 and not stop_event.is_set():
                        more = resp.raw.readline()
                        if not more:
                            break
                        s = more.decode("utf-8", errors="replace") if isinstance(more, bytes) else more
                        data_str += s
                        depth += s.count("{") - s.count("}")
                        guard += 1
                    try:
                        parsed = json.loads(data_str.strip())
                        if isinstance(parsed, dict):
                            data_obj = parsed
                    except Exception:
                        data_obj = {}

                if code == TUMBLE_CODE:
                    if action == "start":
                        _cancel_timer()
                        if not alarm_active:
                            alarm_active = True
                            cur = _current_name()
                            with _lock:
                                _alarms["Alarm uomo a terra"] = "on"
                                _cam_alarms[cur] = "on"
                            print(f"[ALARM-CGI] {ip} ({cur}) TumbleDetection → alarm=on", flush=True)
                            _record_event(ip, cur, "Dahua/TumbleDetection", {"alarm": "on"})
                            _write_alarm_file()
                            _mqtt_publish(cur, "on")
                            # Serena bridge: forward the fall-start as a one-shot voice
                            # command. Inside the `if not alarm_active` guard, so it is
                            # emitted exactly once per fall event (keepalive/reconnect
                            # republishes never enter this branch). Fault-isolated.
                            _mqtt_publish_serena_trigger(cur)
                        # else: già ON, start multipli ignorati

                    elif action == "stop":
                        _cancel_timer()
                        if alarm_active:
                            stop_timer = threading.Timer(STOP_DELAY, _fire_stop)
                            stop_timer.daemon = True
                            stop_timer.start()

                elif code and code not in NOISY:
                    # Log every other real event (person/man-number detection, IVS,
                    # etc.) to the ONVIF events log. The rule name (e.g. SA-3) and
                    # object/count info, when present, come through in `data`.
                    cur = _current_name()
                    evt = {"action": action, "index": parts.get("index", "")}
                    rule_name = data_obj.get("Name") or data_obj.get("RuleName") or ""
                    if rule_name:
                        evt["rule"] = rule_name
                    if data_obj:
                        evt["data"] = data_obj
                    _record_event(ip, cur, f"Dahua/{code}", evt)
                    print(f"[dahua-cgi] {ip} {code};action={action}"
                          f"{(' rule=' + rule_name) if rule_name else ''}", flush=True)

            # Read loop ended without exception (server closed the stream cleanly).
            if not stop_event.is_set() and heartbeat_mode:
                _mark_stream_seen(ip, alive=False)

        except (requests.exceptions.RequestException, OSError, urllib3.exceptions.HTTPError) as e:
            _cancel_timer()
            # Read timeout (socket.timeout / urllib3 ReadTimeoutError) or connection
            # stall. Heartbeat mode: this IS the gap watchdog → not-alive + reconnect.
            # Keepalive mode: reconnect only, liveness owned by the probe (do NOT flip
            # not-alive here).
            if heartbeat_mode:
                _mark_stream_seen(ip, alive=False)
                print(f"[dahua-cgi] {ip} gap/errore stream ({type(e).__name__}) — riconnetto", flush=True)
                stop_event.wait(2)
            else:
                print(f"[dahua-cgi] {ip} stream reset ({type(e).__name__}) — riconnetto", flush=True)
                stop_event.wait(2)
        except Exception as e:
            _cancel_timer()
            print(f"[dahua-cgi] {ip} errore inatteso: {e} — riprovo in 30s", flush=True)
            stop_event.wait(30)
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
            _cgi_responses.pop(ip, None)

    _cancel_timer()
    print(f"[dahua-cgi] {ip} thread terminato (stop richiesto)", flush=True)
def _keepalive_probe_thread(ip: str, port: int, user: str, pwd: str, name: str,
                            stop_event: threading.Event):
    """Fallback-mode liveness: authenticated keepalive probe (magicBox.cgi) on
    KEEPALIVE_INTERVAL. A successful probe advances last_seen and asserts
    stream-liveness; the keepalive-probe gap (not the event-stream silence) is the
    single watchdog for this mode. Auth failures go through the shared backoff."""
    import requests
    from requests.auth import HTTPDigestAuth

    url  = f"http://{ip}:{port}/cgi-bin/magicBox.cgi?action=getSystemInfo"
    auth = HTTPDigestAuth(user, pwd)
    gap_threshold = config.KEEPALIVE_INTERVAL * max(2.0, config.HEARTBEAT_GAP_FACTOR)
    backoff = _Backoff()
    first = True

    while not stop_event.is_set():
        # Auth quarantine (set here on 401/403, or by another path): stop the probe so
        # a rejected credential is never retried into the lockout.
        if _is_auth_failed(ip):
            break
        if first:
            _auth_gate.wait_sync(ip)
            first = False
        auth_failed = False
        auth_status = 0
        try:
            r = requests.get(url, auth=auth, timeout=(5, 10))
            if r.status_code == 200:
                _auth_gate.mark_success(ip)
                backoff.reset()
                _mark_stream_seen(ip, alive=True)
            elif r.status_code in (401, 403):
                auth_failed = True
                auth_status = r.status_code
            else:
                print(f"[keepalive] {ip} HTTP {r.status_code}", flush=True)
        except Exception as e:
            print(f"[keepalive] {ip} probe fallita: {type(e).__name__}", flush=True)

        if auth_failed:
            # Hard auth failure → quarantine and STOP (no backoff-retry into lockout).
            detail = f"Login keepalive fallito (HTTP {auth_status}) — user='{user}'"
            fst = _mark_auth_failed(ip, "Dahua keepalive", detail, name)
            if fst:
                print(f"[keepalive] {ip} ⛔ LOGIN FALLITO HTTP {auth_status}: sospendo il probe "
                      f"per NON far scattare il blocco anti-intrusione. Correggi CAMERA_PASSWORD "
                      f"in .env e riavvia.", flush=True)
            _mark_stream_seen(ip, alive=False)   # sensor is down → detection_ok goes offline
            break

        # Mark not-alive only when the keepalive-probe gap is exceeded.
        with _lock:
            cam = _cameras.get(ip)
            last_seen = cam.get("last_seen", 0.0) if cam else 0.0
        if last_seen and (time.time() - last_seen) > gap_threshold:
            _mark_stream_seen(ip, alive=False)

        stop_event.wait(config.KEEPALIVE_INTERVAL)

    print(f"[keepalive] {ip} thread terminato (stop richiesto)", flush=True)
# ── periodic analytics-rule (fall detection enabled) check ──────────────────────
# Candidate configManager names for the TumbleDetection/StereoBehavior rule.
# The specific name is resolved once (task 5.4) then queried directly thereafter.
# (Exact name confirmed by pre-flight task 1.2 against the deployed firmware.)
_RULE_CONFIG_NAMES = ["VideoAnalyseRule", "StereoBehaviorAnalyse", "TumbleDetection", "AnalyseRules"]
_RULE_KEYWORDS     = ("tumble", "stereo", "fall")
def _cgi_get_config(ip: str, port: int, user: str, pwd: str, cfg_name: str):
    """Blocking configManager.cgi getConfig. Returns (status_code, text)."""
    import requests
    from requests.auth import HTTPDigestAuth
    url = (f"http://{ip}:{port}/cgi-bin/configManager.cgi"
           f"?action=getConfig&name={cfg_name}")
    r = requests.get(url, auth=HTTPDigestAuth(user, pwd), timeout=(5, 10))
    return r.status_code, (r.text or "")
def _parse_rule_enabled(text: str):
    """Parse a Dahua getConfig dump. Returns True (rule present & enabled),
    False (present & disabled), or None (rule not found in this config)."""
    kv: dict[str, str] = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if "=" in ln:
            k, _, v = ln.partition("=")
            kv[k.strip()] = v.strip()

    def _mentions_rule(blob: str) -> bool:
        b = blob.lower()
        return any(w in b for w in _RULE_KEYWORDS)

    # Group by the array-element prefix that owns each `.Enable` flag, and decide
    # from the block that references a tumble/stereo/fall rule.
    result = None
    rule_present = False
    for k, v in kv.items():
        if not k.lower().endswith(".enable"):
            continue
        prefix = k[: k.lower().rfind(".enable")]
        block = {kk: vv for kk, vv in kv.items() if kk == k or kk.startswith(prefix + ".")}
        blob = " ".join(f"{kk}={vv}" for kk, vv in block.items())
        if _mentions_rule(blob):
            rule_present = True
            if v.strip().lower() in ("true", "1"):
                return True   # enabled wins immediately
            result = False
    if rule_present:
        return result if result is not None else True
    # No `.Enable` grouping matched; still detect a bare keyword presence.
    if _mentions_rule(" ".join(f"{k}={v}" for k, v in kv.items())):
        return True
    return None
def _apply_rule_state(ip: str, state):
    """state ∈ {True, False, 'unknown'} — update rule_enabled and refresh detection_ok."""
    with _lock:
        cam = _cameras.get(ip)
        if cam is not None:
            cam["rule_enabled"] = state
    _refresh_detection_ok(ip)
async def _do_rule_check(ip, port, user, pwd, resolved: dict, backoff: "_Backoff"):
    """One rule check. Returns (rule_state, sleep_seconds_before_next).

    rule_state ∈ {True, False, 'unknown'}. Transient failures → 'unknown' with a
    bounded retry burst (2s/4s/8s) then wait the full interval; auth failures →
    'unknown' + the shared common-credential backoff delay (task 5.3)."""
    names = [resolved["name"]] if resolved.get("name") else list(_RULE_CONFIG_NAMES)
    retry_delays = [2, 4, 8]
    attempt = 0
    while True:
        try:
            got_200 = False
            found_state = None
            for cfg_name in names:
                sc, text = await asyncio.to_thread(_cgi_get_config, ip, port, user, pwd, cfg_name)
                if sc in (401, 403):
                    # Hard auth failure → quarantine; the rule task stops (no retry).
                    detail = f"Login rule-check fallito (HTTP {sc}) — user='{user}'"
                    fst = _mark_auth_failed(ip, "Dahua rule-check", detail)
                    if fst:
                        print(f"[rule] {ip} ⛔ LOGIN FALLITO HTTP {sc}: sospendo i controlli "
                              f"per NON far scattare il blocco anti-intrusione. Correggi "
                              f"CAMERA_PASSWORD in .env e riavvia.", flush=True)
                    return ("unknown", None)
                if sc != 200:
                    continue
                got_200 = True
                parsed = _parse_rule_enabled(text)
                if parsed is not None:
                    resolved["name"] = cfg_name   # resolved: query this name only from now on
                    found_state = parsed
                    break
            if found_state is not None:
                _auth_gate.mark_success(ip)
                backoff.reset()
                return (found_state, None)
            if got_200:
                # Camera responded but no fall/tumble rule found → treat as disabled/absent.
                _auth_gate.mark_success(ip)
                backoff.reset()
                return (False, None)
            raise RuntimeError("nessuna risposta 200 dal configManager")
        except Exception as e:
            attempt += 1
            if attempt <= len(retry_delays):
                await asyncio.sleep(retry_delays[attempt - 1])
                continue
            print(f"[rule] {ip} check fallito ({type(e).__name__}) — rule_enabled=unknown", flush=True)
            return ("unknown", None)
async def _rule_check_task(ip: str, port: int, user: str, pwd: str):
    """Per-camera periodic rule-enabled check. First check runs immediately;
    rule_enabled starts 'unknown' (task 5.5)."""
    resolved: dict = {"name": None}
    backoff = _Backoff()
    interval = config.RULE_CHECK_INTERVAL if config.LIVENESS_MODE != "keepalive" else max(60, config.RULE_CHECK_INTERVAL // 2)
    try:
        while True:
            if ip in _removed_ips:
                return
            if _is_auth_failed(ip):
                return   # login failed (here or on another path) — stop rule checks
            await _auth_gate.wait_async(ip)   # first rule check is gated at startup (task 3.10)
            state, override_sleep = await _do_rule_check(ip, port, user, pwd, resolved, backoff)
            _apply_rule_state(ip, state)
            if _is_auth_failed(ip):
                return   # _do_rule_check just quarantined this camera
            await asyncio.sleep(override_sleep if override_sleep is not None else interval)
    except asyncio.CancelledError:
        return
def _stop_camera(ip: str):
    """Teardown a camera's liveness resources in the strict order required by
    task 3.8 so a re-add can never leave a duplicate attach-stream thread:
      (1) set the stop event; (2) interrupt the in-flight request + join the
      thread; (3) ONLY THEN clear _cgi_started; (4) mark detection_ok unavailable.
    """
    ev = _cgi_stop_events.get(ip)
    if ev is not None:
        ev.set()
    resp = _cgi_responses.get(ip)
    if resp is not None:
        try:
            resp.close()   # interrupt a blocking iter_lines read
        except Exception:
            pass
    for reg in (_cgi_threads, _keepalive_threads):
        t = reg.get(ip)
        if t is not None and t.is_alive():
            t.join(timeout=max(5.0, config.HEARTBEAT_GAP_FACTOR * config.HEARTBEAT_INTERVAL + 5))
    # Only after the thread(s) have exited do we clear the started marker.
    with _lock:
        _cgi_started.discard(ip)
        _cgi_stop_events.pop(ip, None)
        _cgi_threads.pop(ip, None)
        _keepalive_threads.pop(ip, None)
        cam = _cameras.get(ip)
        name = cam.get("name", ip) if cam else ip
    _auth_gate.reset(ip)
    _clear_auth_failed(ip)   # a removed camera leaves no sticky quarantine
    # Mark fall_sensor_online off so no stale liveness keeps reporting.
    if mqtt._mqtt_client and name in mqtt._mqtt_detect_discovered:
        try:
            prefix = _cfg["mqtt_prefix"]
            mqtt._mqtt_client.publish(f"{prefix}/{name}/camera_status/fall_sensor_online", payload="off", qos=1, retain=True)
        except Exception:
            pass
    print(f"[cameras] {ip} ({name}) — risorse liveness rilasciate", flush=True)
def _spawn_worker(info: dict):
    """Create a camera worker task and track it (for clean teardown). Must be
    called on the main asyncio loop."""
    ip = info["ip"]
    _worker_tasks[ip] = asyncio.create_task(_camera_worker(info), name=f"cam-{ip}")

def _ensure_rule_task(ip: str, port: int, user: str, pwd: str) -> bool:
    """Start the periodic rule-check task for a camera once (idempotent). Must be
    called on the main asyncio loop."""
    with _lock:
        cam = _cameras.get(ip)
        if not cam or cam.get("_rule_task"):
            return False
        cam["_rule_task"] = True
    _rule_tasks[ip] = asyncio.create_task(_rule_check_task(ip, port, user, pwd), name=f"rule-{ip}")
    return True
async def _teardown_camera(ip: str) -> bool:
    """Fully tear down a camera at runtime: cancel its worker + rule tasks (their
    `finally` closes ONVIF sessions), stop the attach/keepalive threads, mark
    detection_ok unavailable, and drop the camera. Runs on the main loop. Returns
    True if the camera existed. After this the IP is NOT blocked from a future
    manual rescan (no sticky `_removed_ips`)."""
    _removed_ips.add(ip)   # transient: unblock any in-flight worker check
    tasks = []
    for reg in (_worker_tasks, _rule_tasks):
        t = reg.pop(ip, None)
        if t is not None:
            t.cancel()
            tasks.append(t)
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    # _stop_camera joins the attach-stream thread → run off the event loop.
    await asyncio.to_thread(_stop_camera, ip)
    with _lock:
        cam = _cameras.pop(ip, None)
        name = cam.get("name") if cam else None
    if name and name in _cam_alarms:
        _cam_alarms.pop(name, None)
    _removed_ips.discard(ip)   # allow a later manual rescan to rediscover it
    return cam is not None
async def _promote_static(ip: str):
    """Turn a discovered (scan) camera into a persistent static one at runtime:
    mark it static, start its rule-check task, and publish detection_ok. Runs on
    the main loop (scheduled via run_coroutine_threadsafe)."""
    with _lock:
        cam = _cameras.get(ip)
        if not cam:
            return
        cam["_static"] = True
        port = int(cam.get("port", 80))
        user = cam.get("user", "")
        pwd  = cam.get("pass", "")
    _ensure_rule_task(ip, port, user, pwd)
    _refresh_detection_ok(ip)
def _is_fall_topic(topic: str, data: dict) -> bool:
    """True se topic o RuleName nel data corrispondono a fall detection."""
    topic_lc = topic.lower()
    rule_lc  = str(data.get("RuleName", "") or "").lower()
    for pat in FALL_TOPICS:
        pat_lc = pat.lower()
        if pat_lc in topic_lc or pat_lc in rule_lc:
            return True
    return False
def _check_fall_alarm(ip: str, topic: str, data: dict):
    """Se è un evento fall detection, aggiorna _alarms["Alarm uomo a terra"]."""
    if not _is_fall_topic(topic, data):
        return
    # Determina stato on/off dal data
    # Dahua usa IsMotion=true/false, State=active/inactive, o simili
    state_val = (
        data.get("State") or
        data.get("IsMotion") or
        data.get("Alarm") or
        data.get("Value") or
        data.get("Active") or
        ""
    )
    state_str = str(state_val).lower()
    if state_str in ("true", "active", "1", "on", "alarm"):
        alarm_state = "on"
    elif state_str in ("false", "inactive", "0", "off", "normal"):
        alarm_state = "off"
    else:
        # Se non c'è un campo di stato chiaro, considera ON
        alarm_state = "on"

    with _lock:
        _alarms["Alarm uomo a terra"] = alarm_state
    print(f"[ALARM] {ip} fall detection → Alarm uomo a terra={alarm_state}  topic={topic}  data={data}", flush=True)
def _record_event(ip: str, name: str, topic: str, data: dict):
    ts  = datetime.now().isoformat(timespec="milliseconds")
    evt = {"ts": ts, "ip": ip, "name": name, "topic": topic, "data": data}

    with _lock:
        cam = _cameras.get(ip)
        if cam:
            cam["event_count"]  += 1
            cam["last_event_ts"] = ts
            t = cam["topics"].setdefault(topic, {"count": 0, "last_ts": "", "last_data": {}})
            t["count"]    += 1
            t["last_ts"]   = ts
            t["last_data"] = data
            cam.setdefault("last_events", []).append(evt)
            cam["last_events"] = cam["last_events"][-MAX_LOG_CAM:]

        _event_log.append(evt)
        if len(_event_log) > MAX_LOG_GLOBAL:
            _event_log.pop(0)
def _save_loop():
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    while True:
        time.sleep(config.SAVE_INTERVAL)
        try:
            with _lock:
                data = {
                    "saved_at":        datetime.now().isoformat(timespec="seconds"),
                    "scan_subnet":     SCAN_SUBNET,
                    "alarms":          dict(_alarms),
                    "cameras":         {
                        ip: {k: v for k, v in cam.items()
                             if k not in ("last_events", "_analytics_queried")}
                        for ip, cam in _cameras.items()
                    },
                    "event_log_last200": _event_log[-200:],
                }
            tmp = RESULTS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, RESULTS_FILE)
        except Exception as e:
            print(f"[onvif] salvataggio fallito: {e}", flush=True)
async def _mqtt_alarm_keepalive_loop():
    """Pubblica stato allarme ogni 60s solo per cam connesse — HA usa expire_after per rilevare offline."""
    while True:
        await asyncio.sleep(ALARM_KEEPALIVE)
        if not mqtt._mqtt_client:
            continue
        with _lock:
            connected = [
                (cam["name"], _cam_alarms.get(cam["name"], "off"))
                for cam in _cameras.values()
                if cam.get("status") == "connected" or cam.get("simulated")
            ]
        for cam_name, state in connected:
            _mqtt_publish(cam_name, state)
async def _detection_ok_republish_loop():
    """Re-emit each static camera's current detection_ok every DETECTION_REPUBLISH
    seconds (≤ expire_after/2) so a steadily-healthy sensor never lapses to
    unavailable (task 6.4). Immediate publishes on change still happen elsewhere."""
    while True:
        await asyncio.sleep(config.DETECTION_REPUBLISH)
        if not mqtt._mqtt_client:
            continue
        with _lock:
            snapshot = []
            for cam in _cameras.values():
                if not cam.get("_static"):
                    continue
                sim   = bool(cam.get("simulated"))
                alive = True if sim else bool(cam.get("stream_alive", False))
                rule  = True if sim else cam.get("rule_enabled", "unknown")
                snapshot.append((
                    cam["name"],
                    _compute_detection_ok(alive, rule),
                    {"stream_alive": alive, "rule_enabled": rule, "liveness_mode": config.LIVENESS_MODE},
                ))
        for cam_name, state, attrs in snapshot:
            _mqtt_publish_detection_ok(cam_name, state, attrs)
def _serena_fault_tick(now: float):
    """One pass of the multi-shot Serena fault driver over ALL configured cameras
    (not only connected ones), so a camera that never comes up is still flagged.
    Per-camera and independent. Working/fault state comes from the shared
    _camera_working predicate (so simulated cameras count as working and never fault).
    No-op unless the bridge is enabled and the MQTT client exists."""
    if not mqtt._mqtt_client or not _cfg.get("serena_enabled"):
        return
    interval = float(_cfg.get("serena_announce_fault_interval_s", 300.0))
    grace    = float(_cfg.get("serena_announce_fault_grace_s", 60.0))
    for cam_cfg in list(config._static_cameras):
        ip = cam_cfg.get("ip")
        if not ip:
            continue
        working = _camera_working(ip)
        with _lock:
            cam = _cameras.get(ip)
            if cam is None:
                continue
            name      = cam.get("name", ip)
            since     = cam.get("serena_fault_since")
            last_ts   = cam.get("serena_fault_last_ts", 0.0)
            announced = cam.get("serena_fault_announced", False)
        if working:
            if since is None:
                continue   # steadily healthy — nothing to do
            # Was in a fault episode. If we announced ≥1 fault, speak recovery once
            # (gated on announce_fault) and suppress the D6 first-confirm double.
            if announced:
                _mqtt_announce_serena_recovery(name)
            with _lock:
                cam = _cameras.get(ip)
                if cam is not None:
                    if announced:
                        cam["serena_announced"] = True
                    cam["serena_fault_since"]     = None
                    cam["serena_fault_last_ts"]   = 0.0
                    cam["serena_fault_announced"] = False
        else:
            if since is None:
                with _lock:
                    cam = _cameras.get(ip)
                    if cam is not None:
                        cam["serena_fault_since"] = now   # enter episode, no emit yet
                continue
            if (_cfg.get("serena_announce_fault")
                    and (now - since) >= grace
                    and (now - last_ts) >= interval):
                _mqtt_announce_serena_fault(name)
                with _lock:
                    cam = _cameras.get(ip)
                    if cam is not None:
                        cam["serena_fault_last_ts"]   = now
                        cam["serena_fault_announced"] = True


async def _serena_fault_driver_loop():
    """Periodic host for _serena_fault_tick. Tick cadence tracks the configured
    interval (bounded 5..60 s) so the interval/grace gates have adequate resolution."""
    while True:
        interval = float(_cfg.get("serena_announce_fault_interval_s", 300.0))
        tick     = max(5.0, min(60.0, interval))
        await asyncio.sleep(tick)
        _serena_fault_tick(time.time())


async def _main_loop_coro():
    _state._main_loop = asyncio.get_running_loop()
    print(f"[onvif] web UI: http://0.0.0.0:{config.WEB_PORT}", flush=True)

    cred, cams = _load_static_cameras()
    # Publish the resolved common credential + static list back to config so
    # config._get_cred_fallbacks() (manual-scan path) sees the runtime values.
    config._COMMON_CRED = cred
    config._static_cameras = cams

    if config.LIVENESS_MODE == "keepalive":
        print("[onvif] LIVENESS_MODE=keepalive — modalità liveness a garanzia ridotta "
              "(firmware senza heartbeat): liveness via probe autenticato, rule-check più frequente", flush=True)
    print(f"[onvif] liveness: mode={config.LIVENESS_MODE} N={config.HEARTBEAT_INTERVAL}s gap×{config.HEARTBEAT_GAP_FACTOR} "
          f"rule_check={config.RULE_CHECK_INTERVAL}s expire_after={config.DETECTION_EXPIRE}s", flush=True)

    asyncio.create_task(_mqtt_alarm_keepalive_loop(), name="mqtt-alarm-keepalive")
    asyncio.create_task(_detection_ok_republish_loop(), name="detect-republish")
    asyncio.create_task(_serena_fault_driver_loop(), name="serena-fault-driver")

    if config._is_placeholder_pw(cred.get("pass", "")):
        # Common camera password is still the shipped placeholder. Do NOT start any
        # worker: attempting ONVIF/CGI auth with a wrong password repeatedly would trip
        # the Dahua anti-intrusion lockout and block the cameras. The dashboard shows a
        # warning; set a real password in .env (CAMERA_PASSWORD) and
        # restart to enable connections.
        print(f"[onvif] ATTENZIONE: password comune telecamere = "
              f"'{config.DEFAULT_PASSWORD_SENTINEL}' — nessun worker avviato (evito il "
              f"blocco anti-intrusione). Cambia CAMERA_PASSWORD in .env "
              f"e riavvia.", flush=True)
    elif not cams:
        print("[onvif] nessuna telecamera configurata in settings.yaml — nessun worker avviato "
              "(web UI e scan manuale restano disponibili)", flush=True)
    else:
        print(f"[onvif] avvio {len(cams)} telecamere statiche da {SETTINGS_FILE}", flush=True)
        for cam in cams:
            info = {
                "ip":     cam["ip"],
                "name":   cam["name"],
                "user":   cred["user"],
                "pass":   cred["pass"],
                "port":   cred["port"],
                "static": True,
            }
            _spawn_worker(info)

    # Graceful shutdown: on SIGTERM (docker stop/restart) or SIGINT, unsubscribe every
    # live ONVIF PullPoint so the camera frees the slot at once — otherwise the just-
    # restarted process sits in 'connessione…' until the stale subscription expires.
    import signal
    _stop = asyncio.Event()

    async def _graceful_shutdown():
        subs = list(_active_pullpoints.items())
        if subs:
            print(f"[onvif] shutdown — Unsubscribe di {len(subs)} subscription ONVIF", flush=True)
            _active_pullpoints.clear()
            await asyncio.gather(*[_safe_unsubscribe(pp) for _, pp in subs],
                                 return_exceptions=True)
        _stop.set()

    loop = asyncio.get_running_loop()
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(_sig, lambda: asyncio.create_task(_graceful_shutdown()))
        except (NotImplementedError, RuntimeError):
            pass   # signal handlers unavailable (e.g. non-main thread) — degrade gracefully

    # Loop-keeper: with the auto-scanner gone, this awaits the shutdown signal and
    # otherwise keeps the event loop (and the daemon web/save threads) alive —
    # including with zero cameras configured (task 3.6 / spec "Service stays running").
    await _stop.wait()
