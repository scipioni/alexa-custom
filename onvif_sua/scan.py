"""Subnet scanner: TCP probe, ONVIF probe, and a sweep that spawns workers for finds.

Two triggers: the operator's GUI rescan, and — only when `scan.rescan_time_interval`
is non-zero, which is not the default — the periodic `worker._auto_rescan_loop`.
Also hosts the hostname→IP resolution used by `cameras.list` entries configured with
`hostname:` instead of `ip:` (`_match_hostnames` / `_resolve_hostnames`)."""
import asyncio
import ipaddress
import os
import threading
import time
from typing import Optional

from . import config
from .config import ONVIF_PORTS, SCAN_SUBNET, _cfg, _get_cred_fallbacks
from .state import (
    _lock, _cameras, _removed_ips, _operator_removed,
    _mark_auth_failed, _is_auth_failed, _reset_scan_auth_failures,
)
from .worker import _spawn_worker, _record_event, _apply_hostname_resolution

# Manual-scan progress + cooperative cancellation. `_scan_active` is True only
# while `_subnet_scan_once` is running; `_scan_cancel` is set by POST
# /api/scan/stop and checked between probes so the scan exits at a safe point.
# Read these via the module (scan._scan_active) — never `from .scan import`,
# which would capture the value at import time and never see updates.
_scan_active: bool = False
_scan_cancel = threading.Event()
# Completion timestamp of the LAST subnet scan, manual or automatic. The automatic
# rescan interval is measured from here, so a manual rescan pushes the next automatic
# one a full interval into the future ("time passed since the last one", not a fixed
# wall-clock tick). 0.0 = no scan has run yet in this process.
_last_scan_ts: float = 0.0


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
    """Ritorna {ip, name, hostname, user, pass, port} se ONVIF risponde, altrimenti None.

    `hostname` è l'hostname ONVIF riportato dal device (`GetHostname().Name`, trimmed,
    "" se la lettura fallisce) ed è il valore su cui `_resolve_hostnames` fa il match;
    `name` resta il nome di display (hostname se presente, altrimenti il Model)."""
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
            hn = ""
            try:
                hr = await asyncio.wait_for(dev.GetHostname(), timeout=4)
                hn = str(getattr(hr, "Name", "") or "").strip()
                if hn:
                    cam_name = hn
            except Exception:
                pass
            return {"ip": ip, "name": cam_name, "hostname": hn,
                    "user": u, "pass": p, "port": open_port}
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
def _subnet_hosts() -> Optional[list[str]]:
    """Expand the configured scan subnet into host addresses, or None (after logging)
    when it is not a valid CIDR. Shared by the manual scan and hostname resolution."""
    subnet = str(_cfg.get("scan_subnet", SCAN_SUBNET))
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        print(f"[scanner] subnet non valida '{subnet}': {e}", flush=True)
        return None
    return [str(h) for h in network.hosts()]


async def _sweep_probe_all(hosts: list[str]) -> list[dict]:
    """Probe every host concurrently under the shared concurrency semaphore and return
    the successful probe dicts (in `asyncio.gather` completion-independent list order,
    which callers must NOT treat as meaningful — see `_resolve_hostnames`)."""
    sem = asyncio.Semaphore(config.SCAN_CONCUR)

    async def probe_limited(h: str):
        async with sem:
            return await _probe_ip(h)

    results = await asyncio.gather(*[probe_limited(h) for h in hosts], return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


# ── hostname → IP resolution (periodic, driven by worker._hostname_resolve_loop) ──
# Log-volume guards: on a 10-minute cadence an unconditional diagnostic would print
# ~144 identical lines/day per hostname, so both the ambiguity and the unmatched-device
# notices are emitted only on first sight and on change.
_ambiguous_logged: dict[str, tuple] = {}   # canonical hostname → last logged candidate tuple
_unmatched_logged: tuple = ()              # last logged (ip, hostname) set of unmatched devices
_resolve_placeholder_logged: bool = False


def _reset_resolve_log_state():
    """Forget the log-dedupe memory (used by tests)."""
    global _unmatched_logged, _resolve_placeholder_logged
    _ambiguous_logged.clear()
    _unmatched_logged = ()
    _resolve_placeholder_logged = False


def _match_hostnames(found: list[dict], wanted: list[str]) -> dict[str, str]:
    """Pure matching half of `_resolve_hostnames`: given probe results and the configured
    hostnames IN `cameras.list` ORDER, return `{canonical hostname: ip}`.

    Shared with `_subnet_scan_once`, which probes the same subnet and must recognise a
    configured hostname camera that turned up at a NEW address — otherwise it would spawn
    it a second time as a freshly discovered camera, leaving two rows for one device.

    Applies both refusal rules: a hostname reported by ≥2 devices is left out (never
    guessed), and when two configured hostnames land on one IP the entry earlier in
    `cameras.list` keeps it, so scan completion order cannot decide the winner.
    """
    wanted_keys: list[str] = []
    for h in wanted:
        k = str(h or "").strip().lower()
        if k and k not in wanted_keys:
            wanted_keys.append(k)
    if not wanted_keys:
        return {}

    by_hostname: dict[str, list[str]] = {}
    for dev in found:
        k = str(dev.get("hostname") or "").strip().lower()
        if k:
            by_hostname.setdefault(k, []).append(dev["ip"])
    for k in by_hostname:
        by_hostname[k].sort()

    resolved: dict[str, str] = {}
    claimed: dict[str, str] = {}   # ip → hostname that took it (config order wins)
    for key in wanted_keys:
        cands = by_hostname.get(key, [])
        if not cands:
            continue
        if len(cands) > 1:
            sig = tuple(cands)
            if _ambiguous_logged.get(key) != sig:
                print(f"[hostname] AMBIGUO: '{key}' è riportato da {len(cands)} device "
                      f"({', '.join(cands)}) — non ne scelgo nessuno (un nome sbagliato "
                      f"sorveglierebbe la stanza sbagliata). Assegna hostname distinti; "
                      f"riprovo al prossimo giro.", flush=True)
                _ambiguous_logged[key] = sig
            continue
        _ambiguous_logged.pop(key, None)
        ip = cands[0]
        if ip in claimed:
            print(f"[hostname] collisione: '{key}' risolve a {ip}, già assegnato a "
                  f"'{claimed[ip]}' (che precede in cameras.list) — '{key}' resta "
                  f"non risolto", flush=True)
            continue
        claimed[ip] = key
        resolved[key] = ip
    return resolved


def _log_unmatched_devices(found: list[dict], wanted: list[str]):
    """Diagnostic for "the hostname in settings.yaml isn't what the device reports":
    online ONVIF devices matching no configured entry. Deduped — logged on first sight
    and whenever the set changes, not on every sweep."""
    global _unmatched_logged
    wanted_keys = {str(h or "").strip().lower() for h in wanted}
    unmatched = sorted((d["ip"], str(d.get("hostname") or "")) for d in found
                       if str(d.get("hostname") or "").strip().lower() not in wanted_keys)
    sig = tuple(unmatched)
    if unmatched and sig != _unmatched_logged:
        desc = ", ".join(f"{ip}='{hn}'" if hn else f"{ip}=(nessun hostname)" for ip, hn in unmatched)
        print(f"[hostname] device ONVIF online senza voce in cameras.list: {desc}", flush=True)
    _unmatched_logged = sig


async def _resolve_hostnames(wanted: list[str]) -> dict[str, str]:
    """Resolve ONVIF hostnames to their current IPs with ONE subnet sweep.

    `wanted` is the list of configured hostnames **in `cameras.list` order** — that
    order, not scan completion order, is what breaks a two-hostnames-resolve-to-one-IP
    collision, so the winner cannot change from tick to tick. Matching is trimmed and
    case-insensitive against each responding device's `GetHostname().Name`.

    Returns `{canonical hostname: ip}` containing ONLY unambiguously resolved
    hostnames. A hostname reported by ≥2 responding devices is deliberately LEFT OUT
    rather than guessed: `name` is the room identity on every alarm, MQTT topic, HA
    entity and Serena phrase, so attaching to the wrong twin would monitor one room
    while announcing another — a silent wrong. Omitting it fails loudly instead (no
    worker, camera shown down, announced as faulty), and the caller treats a missing
    hostname exactly like a failed resolution: keep the last IP, never migrate.

    This is independent of the manual GUI scan: it does NOT touch `_scan_active` or
    the stop-scan signal, so the dashboard's scan controls are unaffected.
    """
    global _resolve_placeholder_logged
    wanted_keys: list[str] = []
    for h in wanted:
        k = str(h or "").strip().lower()
        if k and k not in wanted_keys:
            wanted_keys.append(k)
    if not wanted_keys:
        return {}

    # Same guard as the manual scan: probing every host with a placeholder password
    # would be a subnet-wide wrong-credential burst (Dahua anti-intrusion lockout).
    if config._password_placeholder_flags()["scan"]:
        if not _resolve_placeholder_logged:
            print(f"[hostname] risoluzione annullata: password ancora "
                  f"'{config.DEFAULT_PASSWORD_SENTINEL}' — "
                  f"{config._placeholder_pw_hint(config._placeholder_pw_var('scan'))}", flush=True)
            _resolve_placeholder_logged = True
        return {}
    _resolve_placeholder_logged = False

    hosts = _subnet_hosts()
    if hosts is None:
        return {}
    found = await _sweep_probe_all(hosts)
    resolved = _match_hostnames(found, wanted_keys)
    _log_unmatched_devices(found, wanted_keys)
    return resolved


async def _subnet_scan_once(automatic: bool = False):
    """One-off subnet scan.

    Two callers: the manual GUI rescan (`/api/rescan`, `automatic=False`) and — only when
    `scan.rescan_time_interval` is set — the periodic `worker._auto_rescan_loop`
    (`automatic=True`). With the interval at its default of 0 the scanner still never
    runs on its own.

    The two modes differ in ONE respect, because a scan spawns a worker for every ONVIF
    device it finds: an automatic scan SKIPS cameras the operator explicitly removed
    (`state._operator_removed`), so a removal is not silently undone one interval later.
    A manual rescan is the operator asking for a full refresh, so it clears that set and
    rediscovers everything — exactly as before this feature existed.
    """
    global _scan_active, _last_scan_ts
    # Refuse to scan while a placeholder password is set — the scanner would try that
    # wrong password against every host and could trip Dahua anti-intrusion lockout.
    if config._password_placeholder_flags()["scan"]:
        print(f"[scanner] scan annullato: password ancora "
              f"'{config.DEFAULT_PASSWORD_SENTINEL}' — "
              f"{config._placeholder_pw_hint(config._placeholder_pw_var('scan'))}", flush=True)
        # Stamp it anyway: an automatic rescan measures its interval from here, so
        # without this the suppressed scan would be retried (and logged) every tick.
        _last_scan_ts = time.time()
        return
    # A fresh manual rescan is the operator's chance to refresh scan-sourced login
    # warnings: drop them so still-unauthenticated hosts are re-probed once (and
    # re-quarantined if they still reject). Camera-worker quarantines are untouched.
    _reset_scan_auth_failures()
    if not automatic:
        # Explicit operator request = full refresh: forget which cameras were removed
        # so they can be rediscovered (unchanged pre-feature behaviour).
        _operator_removed.clear()
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
        kind = "automatico" if automatic else "manuale"
        print(f"[scanner] scan {kind} {subnet} — {len(hosts)} host, {config.SCAN_CONCUR} paralleli...", flush=True)
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

        # A device reporting the ONVIF hostname of a configured `cameras.list` entry is
        # NOT a new discovery — it is that camera, possibly at a new address. Reconcile it
        # first (teardown of the stale IP + respawn on the new one) and exclude its IP from
        # the discovery loop below. Without this the scan spawned a second, non-static
        # worker for it and the dashboard showed the same camera twice: once on the old IP
        # (dead, retrying) and once on the new one. This also means an address change is
        # picked up at scan cadence instead of waiting for the 10-minute resolution tick.
        hostname_cams = [c for c in list(config._static_cameras) if c.get("hostname")]
        owned_ips: set = set()
        if hostname_cams:
            wanted = [c["hostname"] for c in hostname_cams]
            matched = _match_hostnames(found, wanted)
            _log_unmatched_devices(found, wanted)
            owned_ips = await _apply_hostname_resolution(matched, quiet_unresolved=True)
            # Every device REPORTING a configured hostname belongs to that entry, whether
            # or not resolution accepted it. Excluding only the resolved ones would let an
            # AMBIGUOUS hostname (≥2 devices, deliberately unresolved) be adopted by the
            # discovery path instead — spawning both twins under the name the ambiguity
            # rule exists to protect, which is the silent-wrong outcome it refuses.
            wanted_keys = {config._hostname_key(h) for h in wanted}
            owned_ips |= {d["ip"] for d in found
                          if config._hostname_key(d.get("hostname")) in wanted_keys}

        skipped_removed = []
        for cam in found:
            ip = cam["ip"]
            if ip in owned_ips:
                continue   # configured hostname camera — handled above
            with _lock:
                already = ip in _cameras
            # A manual rescan re-adds any camera not currently active — including one
            # previously removed (teardown leaves no sticky block).
            if already or ip in _removed_ips:
                continue
            # An AUTOMATIC scan must not undo an explicit removal: without this the
            # operator's delete would be reverted within one interval, and the camera
            # would reappear (with its MQTT/HA entities) on its own.
            if automatic and ip in _operator_removed:
                skipped_removed.append(ip)
                # Surface it in the dashboard event log too, not just the console: from
                # the operator's side the camera is simply online-and-absent, and the
                # reason (plus the manual-rescan remedy) is otherwise invisible in the UI.
                # One row per skipped camera, so the log's IP/name filters work on it.
                _record_event(ip, str(cam.get("name") or "") or ip,
                              "Scanner/RemovedNotReadded",
                              {"scan": "automatico",
                               "motivo": "rimossa dall'operatore",
                               "azione": "rescan manuale per riscoprirla"})
                continue
            cam["static"] = False   # scan-discovered cameras are NOT persistent static workers
            _spawn_worker(cam)
        if skipped_removed:
            print(f"[scanner] non re-aggiunte {len(skipped_removed)} cam rimosse "
                  f"dall'operatore ({', '.join(skipped_removed)}) — usa il rescan manuale "
                  f"per riscoprirle", flush=True)
    finally:
        _scan_active = False
        # Stamp the completion time on EVERY exit path (completed, aborted, invalid
        # subnet) so a failing scan cannot make the interval check fire in a tight loop.
        _last_scan_ts = time.time()

