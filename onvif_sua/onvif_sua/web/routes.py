"""HTTP routes: all /api/* endpoints and the three server-rendered pages
(login/settings/index). Registered on the shared `app` from app.py."""
import asyncio
import ipaddress
import os
import time
from datetime import datetime

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .app import app, templates, _valid_session, _session_token, _401
from .. import state
from .. import mqtt
from .. import config
from ..config import (
    _cfg, _INT_KEYS, _LIST_KEYS,
    _get_cred_fallbacks, _config_name_conflict, _config_add_camera,
    _config_remove_camera, _check_password, _save_settings_yaml,
    _name_has_reserved_word, _name_voice_collision, _config_hostname_conflict,
    _update_static_camera_entry, _drop_static_camera_entry,
    _config_has_ip_entry, _register_static_camera,
)
from ..state import (
    _lock, _cameras, _event_log, _alarms, _cam_alarms, _removed_ips,
)
from ..mqtt import (
    _mqtt_init, _mqtt_publish, _mqtt_publish_discovery, _mqtt_publish_detection_ok,
    _mqtt_publish_serena_trigger,
)
from ..worker import _teardown_camera, _promote_static, _record_event, _write_alarm_file
from .. import scan
from ..scan import _subnet_scan_once
from ..connect import _safe_close


@app.get("/api/cameras")
def api_cameras(request: Request):
    if not _valid_session(request): return JSONResponse(_401, status_code=401)
    with _lock:
        # Credential-redacted: see state._CAM_PRIVATE_KEYS. The entry holds the working
        # `user`/`pass` and this body is readable in any browser network tab or proxy log.
        return JSONResponse([state._public_cam(c) for c in _cameras.values()])


@app.get("/api/events")
def api_events(request: Request, limit: int = 500):
    if not _valid_session(request): return JSONResponse(_401, status_code=401)
    with _lock:
        return JSONResponse(_event_log[-limit:])


@app.get("/api/status")
def api_status(request: Request):
    if not _valid_session(request): return JSONResponse(_401, status_code=401)
    # Snapshot the quarantine list OUTSIDE the lock below — _auth_failures_list()
    # takes _lock itself and the threading.Lock is not reentrant.
    auth_failures = state._auth_failures_list()
    rescan_interval = config._rescan_interval()
    rescan_in = (max(0.0, round(scan._last_scan_ts + rescan_interval - time.time(), 1))
                 if rescan_interval > 0 else None)
    with _lock:
        return JSONResponse({
            "scan_subnet":   _cfg["scan_subnet"],
            # Credential-redacted: see state._CAM_PRIVATE_KEYS.
            "cameras":       state._public_cameras(_cameras),
            "event_log":     _event_log[-200:],
            # Placeholder-password guard: which credentials still hold the shipped
            # 'default_to_change' sentinel (workers/scan suppressed while true).
            "password_warning": config._password_placeholder_flags(),
            # Cameras quarantined after a login/auth failure — retries suspended so a
            # wrong password can't trip the anti-intrusion lockout. Drives the UI warning.
            "auth_failures": auth_failures,
            # Additive: True while a subnet scan is running — drives the dashboard's
            # stop-scan button. Existing consumers ignore it.
            "scan_active":   scan._scan_active,
            # Automatic-rescan state (additive): the effective interval in seconds
            # (0 = disabled) and the seconds left before the next one, so the dashboard
            # can show when it will happen. None when disabled.
            "rescan_interval": rescan_interval,
            "rescan_in":       rescan_in,
        })


@app.post("/api/events/clear")
def api_events_clear(request: Request):
    if not _valid_session(request): return JSONResponse(_401, status_code=401)
    with _lock:
        _event_log.clear()
        for cam in _cameras.values():
            cam["last_events"] = []
            cam["event_count"] = 0
            cam["topics"] = {}
            cam["last_event_ts"] = None
    return JSONResponse({"status": "cleared"})


@app.post("/api/cameras/{ip}/rename")
async def api_rename_camera(ip: str, request: Request):
    body = await request.json()
    new_name = body.get("name", "").strip()
    if not new_name:
        return JSONResponse({"status": "error", "detail": "Nome vuoto"}, status_code=400)
    # ONVIF accetta solo lettere, cifre, trattini (RFC 952/1123)
    import re
    new_name = re.sub(r"[^a-zA-Z0-9\-]", "-", new_name)[:63].strip("-")
    if not new_name:
        return JSONResponse({"status": "error", "detail": "Nome non valido dopo sanitizzazione"}, status_code=400)

    # A camera configured by ONVIF `hostname` instead of a static `ip` is addressed
    # here by its RESOLVED IP, and its cameras.list entry has no `ip` key at all — so
    # every config helper below must locate it by hostname (matching on IP would
    # render the literal "None" and silently act on "a different camera"). None for a
    # static-`ip` camera, which keeps the pre-existing behaviour exactly.
    cfg_hostname = state._hostname_for_ip(ip)

    # Serena bridge naming rules — enforced BEFORE touching the device (SetHostname)
    # or settings.yaml, mirroring the name-conflict alert below. The camera name feeds
    # the spoken phrase, so it must not contain 'camera' nor collide (after voice
    # normalization) with another camera.
    if _name_has_reserved_word(new_name):
        return JSONResponse(
            {"status": "error",
             "detail": "Il nome non può contenere 'camera' (usa il nome della stanza, es. 'cucina')"},
            status_code=400,
        )
    voice_clash = _name_voice_collision(ip, new_name, cfg_hostname)
    if voice_clash:
        return JSONResponse(
            {"status": "error",
             "detail": f"Il nome '{new_name}' coincide (dopo normalizzazione) con la telecamera {voice_clash}"},
            status_code=400,
        )

    # Renaming sets the camera's ONVIF device hostname — the value the resolution
    # sweep matches on. Renaming THIS camera to ANOTHER entry's configured hostname
    # would make it answer that entry's resolution (and make that entry permanently
    # ambiguous), so refuse before the device is touched. Its own hostname is fine.
    host_clash = _config_hostname_conflict(new_name, cfg_hostname)
    if host_clash:
        return JSONResponse(
            {"status": "error",
             "detail": f"Il nome '{new_name}' è l'hostname configurato della telecamera "
                       f"{host_clash} — rinominando questa risponderebbe al posto di quella"},
            status_code=409,
        )

    with _lock:
        cam = _cameras.get(ip)
    if not cam:
        return JSONResponse({"status": "error", "detail": "Camera non trovata"}, status_code=404)

    # Every rename is persisted to settings.yaml (renaming saves the camera, even
    # one not saved before). Block a name already used by ANOTHER saved camera
    # BEFORE touching the device — protects the unique MQTT/HA identity.
    clash_ip = _config_name_conflict(ip, new_name, cfg_hostname)
    if clash_ip:
        return JSONResponse(
            {"status": "error", "detail": f"Nome '{new_name}' già usato dalla telecamera {clash_ip}"},
            status_code=409,
        )

    from onvif import ONVIFCamera
    wsdl = os.path.join(os.path.dirname(__import__("onvif").__file__), "wsdl")
    c = None
    try:
        c = ONVIFCamera(ip, cam["port"], cam["user"], cam["pass"], wsdl_dir=wsdl)
        await asyncio.wait_for(c.update_xaddrs(), timeout=8)
        dev = await c.create_devicemgmt_service()
        await asyncio.wait_for(dev.SetHostname({"Name": new_name}), timeout=8)
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
    finally:
        await _safe_close(c)

    # Verifica che la cam abbia effettivamente applicato il nuovo nome
    actual_name = None
    c2 = None
    try:
        c2 = ONVIFCamera(ip, cam["port"], cam["user"], cam["pass"], wsdl_dir=wsdl)
        await asyncio.wait_for(c2.update_xaddrs(), timeout=6)
        dev2 = await c2.create_devicemgmt_service()
        hr = await asyncio.wait_for(dev2.GetHostname(), timeout=4)
        actual_name = str(getattr(hr, "Name", "") or "").strip()
    except Exception:
        pass
    finally:
        await _safe_close(c2)

    verified = (actual_name == new_name) if actual_name is not None else None

    with _lock:
        _cameras[ip]["name"] = new_name
        _cameras[ip]["name_verified"] = verified is not False
        old_name = cam["name"]
        if old_name in _cam_alarms:
            _cam_alarms[new_name] = _cam_alarms.pop(old_name)

    # For a hostname-configured camera the device hostname IS the discovery key, so it
    # has just changed with the name: rewrite the entry's `hostname` in the same save.
    # Write what the device actually REPORTS (self-healing when firmware normalises or
    # truncates the requested name); only a failed verification read leaves a guess.
    new_hostname = None
    if cfg_hostname:
        if actual_name:
            new_hostname = actual_name
        else:
            new_hostname = new_name
            print(f"[hostname] {ip} — rilettura hostname fallita dopo SetHostname: "
                  f"scrivo '{new_hostname}' in settings.yaml al posto di '{cfg_hostname}' "
                  f"senza conferma dal device — verifica la voce se non si risolve", flush=True)

    # Renaming persists the camera to settings.yaml — and, if it wasn't saved
    # before, promotes it to a running static worker (mirrors the 💾 button). No
    # manual save needed.
    ok, msg = _config_add_camera(ip, new_name, int(cam["port"]),
                                hostname=cfg_hostname, set_hostname=new_hostname)
    if ok:
        _removed_ips.discard(ip)
        state._operator_removed.discard(ip)   # renaming saves the camera: wanted again
        # Keep the in-memory static list (what the resolution loop iterates) in step,
        # and move the cached resolved IP to the new hostname key. Leaving a stale key
        # would make the next sweep see a never-resolved hostname and spawn a SECOND
        # worker on the IP that already has one. The worker itself is untouched — the
        # IP did not change, only the key it is cached under.
        _update_static_camera_entry(ip, new_name, hostname=cfg_hostname,
                                    set_hostname=new_hostname)
        if cfg_hostname and new_hostname:
            state._rekey_resolved_hostname(cfg_hostname, new_hostname)
        if state._main_loop:
            asyncio.run_coroutine_threadsafe(_promote_static(ip), state._main_loop)

    print(f"[onvif] {ip} rinominata: {cam['name']} → {new_name} "
          f"(verifica: {actual_name!r}, settings.yaml: {msg if ok else 'errore'})", flush=True)
    if not ok and cfg_hostname:
        # The DEVICE has already been renamed but the config was not: the entry still
        # names the old hostname and will no longer resolve. Report the rename as
        # failed and log the device's new hostname so it can be repaired by hand.
        print(f"[hostname] ATTENZIONE: {ip} ha ora hostname ONVIF "
              f"'{new_hostname}' ma settings.yaml non è stato aggiornato ({msg}) — "
              f"correggi a mano 'hostname: {new_hostname}' nella voce '{cfg_hostname}'",
              flush=True)
        return JSONResponse({"status": "error", "name": new_name, "actual": actual_name,
                             "verified": verified, "saved": False,
                             "detail": f"{msg} — hostname del device ora '{new_hostname}': "
                                       f"correggi settings.yaml a mano"},
                            status_code=500)
    return JSONResponse({"status": "ok", "name": new_name, "actual": actual_name,
                         "verified": verified, "saved": ok, "detail": msg})


@app.post("/api/cameras/{ip}/save")
async def api_save_camera(ip: str, request: Request):
    """Persist a (discovered) camera to the settings.yaml `cameras` block and
    promote it to a persistent static worker at runtime."""
    if not _valid_session(request):
        return JSONResponse(_401, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    with _lock:
        cam = _cameras.get(ip)
        if cam is None:
            return JSONResponse({"status": "error", "detail": "Camera non trovata"}, status_code=404)
        name = (body.get("name") or cam.get("name") or "").strip()
        port = int(cam.get("port", 80))
        dev_hostname = str(cam.get("onvif_hostname", "") or "").strip()
    if not name or name == ip:
        return JSONResponse({"status": "error", "detail": "Assegna prima un nome alla telecamera"}, status_code=400)

    # An already-configured hostname camera is addressed here by its resolved IP; pass
    # the hostname so its existing entry is updated instead of a duplicate `{ip, name}`
    # row being appended (None for a static/discovered camera — unchanged behaviour).
    cfg_hostname = state._hostname_for_ip(ip)

    # Serena bridge naming rules (see api_rename_camera). _config_add_camera also
    # enforces these as the shared chokepoint, but surface a clear 400 here.
    if _name_has_reserved_word(name):
        return JSONResponse(
            {"status": "error",
             "detail": "Il nome non può contenere 'camera' (usa il nome della stanza, es. 'cucina')"},
            status_code=400,
        )
    voice_clash = _name_voice_collision(ip, name, cfg_hostname)
    if voice_clash:
        return JSONResponse(
            {"status": "error",
             "detail": f"Il nome '{name}' coincide (dopo normalizzazione) con la telecamera {voice_clash}"},
            status_code=400,
        )

    # Which address form to persist. A camera with NO entry yet is saved as a `hostname:`
    # entry whenever the device reported an ONVIF hostname, so the periodic resolution
    # keeps its address current and a DHCP lease change never orphans the entry. An entry
    # that ALREADY exists keeps its current form: silently converting a static `ip:` entry
    # to `hostname:` (or back) would change how it is addressed without being asked.
    fell_back_to_ip = False
    if cfg_hostname:
        append_hostname, saved_hostname = None, cfg_hostname       # existing hostname entry
    elif _config_has_ip_entry(ip):
        append_hostname, saved_hostname = None, None               # existing static entry
    else:
        append_hostname = dev_hostname or None                     # new entry
        saved_hostname = append_hostname
        fell_back_to_ip = not append_hostname

    ok, msg = _config_add_camera(ip, name, port, hostname=cfg_hostname,
                                 append_hostname=append_hostname)
    if not ok:
        return JSONResponse({"status": "error", "detail": msg}, status_code=409)
    # Make the entry visible to the runtime loops without a restart, and seed the
    # hostname→IP cache with the address it answers at right now, so the camera keeps
    # running and a later rename/remove finds its entry by hostname.
    _register_static_camera(ip, name, hostname=saved_hostname)
    if saved_hostname:
        state._set_resolved_ip(saved_hostname, ip)
    # Saving is the opposite of removing: this camera is wanted again, so let the
    # automatic rescan see it once more.
    state._operator_removed.discard(ip)

    # Promote to a static worker at runtime (rule-check + detection_ok) on the loop.
    if state._main_loop:
        asyncio.run_coroutine_threadsafe(_promote_static(ip), state._main_loop)
    _removed_ips.discard(ip)
    form = f"hostname: {saved_hostname}" if saved_hostname else f"ip: {ip}"
    print(f"[cameras] {ip} ({name}) — salvata in settings.yaml ({msg}, {form})", flush=True)
    if fell_back_to_ip:
        print(f"[cameras] {ip} — nessun hostname ONVIF disponibile: salvata con ip statico "
              f"(un cambio di lease DHCP richiederà una modifica manuale)", flush=True)
    return JSONResponse({"status": "ok", "name": name, "detail": msg,
                         "hostname": saved_hostname or "", "address_form": form})


@app.post("/api/cameras/{ip}/remove")
async def api_remove_camera(ip: str, request: Request):
    """Remove a camera from the runtime list AND from the settings.yaml config."""
    if not _valid_session(request):
        return JSONResponse(_401, status_code=401)
    with _lock:
        name = _cameras.get(ip, {}).get("name", ip)
    # A hostname-configured camera's entry has no `ip` to match: without the hostname
    # the entry survives the removal, and since the ENTRY drives resolution the next
    # sweep respawns the camera within one interval — it would come back by itself.
    cfg_hostname = state._hostname_for_ip(ip)
    removed_cfg = _config_remove_camera(ip, hostname=cfg_hostname)
    if removed_cfg:
        _drop_static_camera_entry(ip, hostname=cfg_hostname)
        if cfg_hostname:
            state._drop_resolved_hostname(cfg_hostname)
    # Remember the explicit removal so the AUTOMATIC periodic rescan (when enabled) does
    # not rediscover and respawn this camera within one interval, quietly undoing the
    # delete. A manual rescan still rediscovers it — that is the operator asking.
    state._operator_removed.add(ip)

    # Runtime teardown on the main loop: cancel worker + rule tasks (closing their
    # ONVIF sessions), stop the attach/keepalive threads, mark detection_ok
    # unavailable, drop the camera. Leaves NO sticky block, so a later manual
    # rescan can rediscover this IP.
    existed = False
    if state._main_loop:
        fut = asyncio.run_coroutine_threadsafe(_teardown_camera(ip), state._main_loop)
        try:
            existed = bool(fut.result(timeout=25))
        except Exception as e:
            print(f"[cameras] {ip} — teardown errore: {e}", flush=True)
    print(f"[cameras] {ip} ({name}) — rimossa (config={removed_cfg}, runtime={existed})", flush=True)
    return JSONResponse({
        "status": "ok",
        "removed_config": removed_cfg,
        "removed_runtime": existed,
    })


@app.post("/api/cameras/{ip}/simulate")
async def api_simulate_camera(ip: str, request: Request):
    """Test aid: toggle a fake 'camera connected + person-has-fallen' state for a
    camera so the Home Assistant flow can be exercised WITHOUT real hardware.

    Body: {"on": bool}. When ON, publishes the same MQTT a real connected camera
    reporting a fall would (fall alarm `on`, fall-sensor online, retained), and the
    keep-alive loops republish it while the toggle stays on. When OFF, publishes the
    fall alarm `off` and the detector as not-active, and hands status back to the real
    worker. Purely in-memory / ephemeral — never written to settings.yaml."""
    if not _valid_session(request):
        return JSONResponse(_401, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    turn_on = bool(body.get("on"))

    with _lock:
        cam = _cameras.get(ip)
        if cam is None:
            return JSONResponse({"status": "error", "detail": "Telecamera sconosciuta"},
                                status_code=404)
        name = cam.get("name", ip)
        cam["simulated"] = turn_on
        if turn_on:
            cam["status"]       = "connected"
            cam["stream_alive"] = True
            cam["rule_enabled"] = True
            cam["detection_ok"] = "on"
            _cam_alarms[name]   = "on"
            _alarms["Alarm uomo a terra"] = "on"
        else:
            # Hand status back to the real worker. The worker only re-asserts status
            # at a (re)connect transition and otherwise sits in its PullMessages loop,
            # so forcing "connecting" here would stick until the next ONVIF drop. Use
            # the live ONVIF state instead: a tracked pullpoint means it's connected
            # right now. stream_alive/rule_enabled/detection_ok are re-derived by the
            # CGI + rule tasks within one interval.
            cam["status"]       = "connected" if ip in state._active_pullpoints else "connecting"
            cam["stream_alive"] = False
            cam["rule_enabled"] = "unknown"
            cam["detection_ok"] = None
            _cam_alarms[name]   = "off"
            _alarms["Alarm uomo a terra"] = "on" if any(v == "on" for v in _cam_alarms.values()) else "off"

    if turn_on:
        attrs = {"stream_alive": True, "rule_enabled": True,
                 "liveness_mode": config.LIVENESS_MODE, "simulated": True}
        _mqtt_publish_discovery(name)
        _mqtt_publish(name, "on")
        # Also drive the Serena bridge, so the simulate button is a full end-to-end
        # test of the voice flow (not just the HA fall state). No-op unless the bridge
        # is enabled/configured. Mirrors the real fall-start emit.
        _mqtt_publish_serena_trigger(name)
        _mqtt_publish_detection_ok(name, "on", attrs)
        _record_event(ip, name, "SIMULATION/TumbleDetection", {"alarm": "on", "simulated": True})
        print(f"[SIM] {ip} ({name}) — simulazione ON (presenza + caduta)", flush=True)
    else:
        attrs = {"stream_alive": False, "rule_enabled": "unknown",
                 "liveness_mode": config.LIVENESS_MODE, "simulated": False}
        _mqtt_publish(name, "off")
        _mqtt_publish_detection_ok(name, "off", attrs)
        _record_event(ip, name, "SIMULATION/TumbleDetection", {"alarm": "off", "simulated": True})
        print(f"[SIM] {ip} ({name}) — simulazione OFF", flush=True)
    _write_alarm_file()

    return JSONResponse({"status": "ok", "ip": ip, "simulated": turn_on})


@app.get("/api/config")
def api_config_get(request: Request):
    if not _valid_session(request): return JSONResponse(_401, status_code=401)
    safe = dict(_cfg)
    if safe.get("mqtt_pass"):
        safe["mqtt_pass"] = "********"
    safe.pop("web_password", None)   # mai esposta
    safe["mqtt_connected"] = bool(mqtt._mqtt_client and mqtt._mqtt_client.is_connected())
    # Credenziali: maschera password ma mantieni struttura
    creds = _get_cred_fallbacks()
    safe["cam_credentials"] = [{"user": u, "pass": "*" * min(4, len(p)) if p else ""} for u, p in creds]
    safe["cam_credentials_count"] = len(creds)
    return JSONResponse(safe)


@app.post("/api/config")
async def api_config_post(request: Request):
    if not _valid_session(request):
        return JSONResponse({"status": "error", "detail": "Non autenticato"}, status_code=401)
    body = await request.json()
    # scan_subnet is kept only for the manual GUI scan; it no longer starts an
    # automatic scanner (task 3.1/3.4). cam_credentials is NOT accepted — the scan
    # credential is env-sourced (.env SCAN_USER/SCAN_PASSWORD); a submitted value is
    # silently ignored.
    allowed = {"mqtt_host", "mqtt_port", "mqtt_user", "mqtt_pass", "mqtt_prefix",
               "scan_subnet", "rescan_time_interval"}
    for k, v in body.items():
        if k not in allowed:
            continue
        if k in _LIST_KEYS:
            new_val = v   # lista di dict, passa così
        elif k in _INT_KEYS:
            new_val = int(v)
        else:
            new_val = str(v)
        _cfg[k] = new_val

    # Valida subnet prima di salvare
    if "scan_subnet" in body:
        try:
            ipaddress.ip_network(_cfg["scan_subnet"], strict=False)
        except ValueError as e:
            return JSONResponse({"status": "error", "detail": f"Subnet non valida: {e}"}, status_code=400)

    # Reject a negative interval outright rather than silently coercing it to "disabled":
    # the operator asked for something impossible and should be told.
    if "rescan_time_interval" in body and int(_cfg["rescan_time_interval"]) < 0:
        return JSONResponse({"status": "error",
                             "detail": "rescan_time_interval non può essere negativo "
                                       "(0 = rescan automatico disabilitato)"},
                            status_code=400)

    _save_settings_yaml()
    _mqtt_init()
    return JSONResponse({
        "status":        "ok",
        "scan_subnet":   _cfg["scan_subnet"],
        "mqtt_host":     _cfg["mqtt_host"],
        # Effective value after the safety floor, so the caller sees what will be used.
        "rescan_time_interval": config._rescan_interval(),
    })


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _valid_session(request):
        return RedirectResponse("/settings", status_code=302)
    return templates.TemplateResponse(
        request, "login.html", {"asset_version": _cfg.get("asset_version", "1")})


@app.post("/api/login")
async def api_login(request: Request):
    body = await request.json()
    pwd = body.get("password", "")
    if not _check_password(pwd, _cfg.get("web_password", "")):
        return JSONResponse({"status": "error", "detail": "Password errata"}, status_code=401)
    resp = JSONResponse({"status": "ok"})
    resp.set_cookie("onvif_session", _session_token(), httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("onvif_session")
    return resp


# The web login password is env-sourced (GUI_PASSWORD in .env); there is no in-GUI
# change-password flow. To change it, edit .env and restart.


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if not _valid_session(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request, "settings.html", {"asset_version": _cfg.get("asset_version", "1")})


@app.get("/alarm.json")
def serve_alarm_json():
    with _lock:
        data = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            **_cam_alarms,
        }
    return JSONResponse(data)


@app.get("/api/alarms")
def api_alarms():
    """Ritorna lo stato degli allarmi nominati (es. Alarm uomo a terra) e la lista
    delle telecamere attualmente in allarme (da `_cam_alarms`)."""
    with _lock:
        named   = dict(_alarms)
        cams_on = sorted(n for n, s in _cam_alarms.items() if s == "on")
    return JSONResponse({"alarms": named, "cameras_on": cams_on})


@app.post("/api/rescan")
def api_rescan(request: Request):
    """Forza un nuovo scan immediato della subnet (azione manuale dell'operatore)."""
    if not _valid_session(request): return JSONResponse(_401, status_code=401)
    if not state._main_loop:
        return JSONResponse({"error": "loop non pronto"}, status_code=503)
    asyncio.run_coroutine_threadsafe(_subnet_scan_once(), state._main_loop)
    return JSONResponse({"status": "scan avviato", "subnet": _cfg["scan_subnet"]})


@app.post("/api/scan/stop")
def api_scan_stop(request: Request):
    """Richiede l'interruzione cooperativa di uno scan manuale in corso.

    Se uno scan è attivo, imposta il segnale di stop (`_subnet_scan_once` esce
    prima del prossimo probe) e ritorna `stopping`. Se nessuno scan è in corso è
    un no-op (non un errore): ritorna `idle` — il pulsante potrebbe essere premuto
    in una race proprio mentre lo scan termina."""
    if not _valid_session(request): return JSONResponse(_401, status_code=401)
    if scan._scan_active:
        scan._scan_cancel.set()
        return JSONResponse({"status": "stopping"})
    return JSONResponse({"status": "idle"})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not _valid_session(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request, "index.html", {"asset_version": _cfg.get("asset_version", "1")})


@app.get("/favicon.ico")
def favicon():
    return HTMLResponse("", status_code=204)
