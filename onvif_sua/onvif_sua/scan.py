"""Manual, operator-triggered subnet scanner (GUI rescan only — never automatic):
TCP probe, ONVIF probe, and a one-off subnet sweep that spawns workers for finds."""
import asyncio
import ipaddress
import os
import threading
import time
from typing import Optional

from . import config
from .config import ONVIF_PORTS, SCAN_SUBNET, _cfg, _get_cred_fallbacks
from .state import (
    _lock, _cameras, _removed_ips,
    _mark_auth_failed, _is_auth_failed, _reset_scan_auth_failures,
)
from .worker import _spawn_worker

# Manual-scan progress + cooperative cancellation. `_scan_active` is True only
# while `_subnet_scan_once` is running; `_scan_cancel` is set by POST
# /api/scan/stop and checked between probes so the scan exits at a safe point.
# Read these via the module (scan._scan_active) — never `from .scan import`,
# which would capture the value at import time and never see updates.
_scan_active: bool = False
_scan_cancel = threading.Event()


async def _tcp_probe(ip: str, port: int, timeout: float = 1.2) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False
async def _probe_ip(ip: str) -> Optional[dict]:
    """Ritorna {ip, name, user, pass, port} se ONVIF risponde, altrimenti None."""
    from onvif import ONVIFCamera
    wsdl = os.path.join(os.path.dirname(__import__("onvif").__file__), "wsdl")

    # Skip an IP already quarantined for a login failure — re-authenticating a known-
    # wrong credential is exactly what would trip the camera's anti-intrusion lockout.
    if _is_auth_failed(ip):
        return None

    open_port = None
    for port in ONVIF_PORTS:
        if await _tcp_probe(ip, port):
            open_port = port
            break
    if open_port is None:
        return None

    reachable = False   # ONVIF answered but no credential authenticated
    for u, p in _get_cred_fallbacks():
        c = None
        try:
            c = ONVIFCamera(ip, open_port, u, p, wsdl_dir=wsdl)
            await asyncio.wait_for(c.update_xaddrs(), timeout=5)
            reachable = True
            # update_xaddrs does NOT authenticate — validate the credential with an
            # auth-required call before accepting it, otherwise we'd return the wrong
            # password and every later ONVIF/CGI/rename call would 401.
            dev = await c.create_devicemgmt_service()
            try:
                di = await asyncio.wait_for(dev.GetDeviceInformation(), timeout=4)
            except Exception:
                continue   # credential rejected → try the next one
            cam_name = str(getattr(di, "Model", "") or "").strip()
            try:
                hr = await asyncio.wait_for(dev.GetHostname(), timeout=4)
                hn = str(getattr(hr, "Name", "") or "").strip()
                if hn:
                    cam_name = hn
            except Exception:
                pass
            return {"ip": ip, "name": cam_name, "user": u, "pass": p, "port": open_port}
        except Exception:
            pass
        finally:
            if c is not None:
                try:
                    await c.close()
                except Exception:
                    pass
    if reachable:
        # ONVIF answered but every credential was rejected — quarantine the IP so a
        # later scan won't re-hammer it, and surface the warning in the log + web UI.
        detail = "Login scan fallito: ONVIF raggiungibile ma nessuna credenziale valida"
        first = _mark_auth_failed(ip, "scan", detail)
        if first:
            print(f"[scanner] {ip} ⛔ LOGIN FALLITO: nessuna credenziale valida. Non riprovo "
                  f"(evito il blocco anti-intrusione). Correggi SCAN_PASSWORD/CAMERA_PASSWORD "
                  f"in .env e riavvia.", flush=True)
    return None
async def _subnet_scan_once():
    """One-off subnet scan — invoked ONLY by the manual GUI rescan (`/api/rescan`).
    Automatic/periodic scanning is disabled; this never runs on its own."""
    # Refuse to scan while a placeholder password is set — the scanner would try that
    # wrong password against every host and could trip Dahua anti-intrusion lockout.
    if config._password_placeholder_flags()["scan"]:
        print(f"[scanner] scan annullato: password ancora "
              f"'{config.DEFAULT_PASSWORD_SENTINEL}' — impostane una reale prima di scansionare", flush=True)
        return
    global _scan_active
    # A fresh manual rescan is the operator's chance to refresh scan-sourced login
    # warnings: drop them so still-unauthenticated hosts are re-probed once (and
    # re-quarantined if they still reject). Camera-worker quarantines are untouched.
    _reset_scan_auth_failures()
    # Cooperative-cancel setup: clear any stale stop request and mark the scan
    # active. The finally clears the flag on every exit path (completion, abort,
    # or the invalid-subnet guard inside the try).
    _scan_cancel.clear()
    _scan_active = True
    try:
        sem = asyncio.Semaphore(config.SCAN_CONCUR)
        subnet = str(_cfg.get("scan_subnet", SCAN_SUBNET))
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except ValueError as e:
            print(f"[scanner] subnet non valida '{subnet}': {e}", flush=True)
            return

        hosts = list(network.hosts())
        print(f"[scanner] scan manuale {subnet} — {len(hosts)} host, {config.SCAN_CONCUR} paralleli...", flush=True)
        t0 = time.time()

        async def probe_limited(h):
            # Cooperative cancel: probes are queued behind the semaphore, so each
            # checks the stop signal as it starts (i.e. before its IP probe) and
            # skips cleanly when set. Probes already completed keep their result,
            # so cameras discovered before the stop are preserved.
            if _scan_cancel.is_set():
                return None
            async with sem:
                if _scan_cancel.is_set():
                    return None
                return await _probe_ip(str(h))

        results = await asyncio.gather(*[probe_limited(h) for h in hosts], return_exceptions=True)
        found = [r for r in results if isinstance(r, dict)]

        elapsed = time.time() - t0
        if _scan_cancel.is_set():
            print(f"[scanner] scan interrotto — {len(found)} cam trovate prima dello stop ({elapsed:.1f}s)", flush=True)
        else:
            print(f"[scanner] trovate {len(found)} cam ONVIF in {elapsed:.1f}s", flush=True)
        for cam in found:
            print(f"  {cam['ip']:20s}  porta {cam['port']}  [{cam['user']}]", flush=True)

        for cam in found:
            ip = cam["ip"]
            with _lock:
                already = ip in _cameras
            # A manual rescan re-adds any camera not currently active — including one
            # previously removed (teardown leaves no sticky block).
            if not already and ip not in _removed_ips:
                cam["static"] = False   # manual-scan cameras are NOT persistent static workers
                _spawn_worker(cam)
    finally:
        _scan_active = False

