"""Shared mutable runtime state — the camera registry, event log, alarm state,
task/thread registries, the global lock, and the auth backoff/gate. Leaf module
(imports only config scalars) so every other module can import it without cycles."""
import asyncio
import threading
import time
from typing import Optional

from .config import AUTH_BACKOFF_START, AUTH_BACKOFF_CAP, AUTH_GATE_WINDOW


# ── auth-failure backoff (capped exponential, shared by common-credential paths) ─
class _Backoff:
    """Capped exponential backoff; reset() on the first success of a path."""
    def __init__(self, start: float = AUTH_BACKOFF_START, cap: float = AUTH_BACKOFF_CAP):
        self._start = start
        self._cap   = cap
        self._cur: Optional[float] = None
    def next_delay(self) -> float:
        if self._cur is None:
            self._cur = self._start
        else:
            self._cur = min(self._cur * 2, self._cap)
        return self._cur
    def reset(self):
        self._cur = None
    def is_fresh(self) -> bool:
        """True if no failure has been recorded since the last reset."""
        return self._cur is None


class _AuthGate:
    """Startup auth gate: caps common-credential auth attempts to ≤ 1 per
    AUTH_GATE_WINDOW per camera until that camera's first successful auth,
    so the three auth paths (ONVIF connect, CGI attach, first rule check) do
    not fire a synchronized burst that trips Dahua anti-intrusion lockout."""
    def __init__(self, window: float = AUTH_GATE_WINDOW):
        self._window = window
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}   # ip → earliest next attempt ts
        self._passed: set[str] = set()      # ips past first success
    def _reserve(self, ip: str) -> float:
        with self._lock:
            if ip in self._passed:
                return 0.0
            now = time.time()
            start = max(now, self._next.get(ip, 0.0))
            self._next[ip] = start + self._window
            return start - now
    def wait_sync(self, ip: str):
        d = self._reserve(ip)
        if d > 0:
            time.sleep(d)
    async def wait_async(self, ip: str):
        d = self._reserve(ip)
        if d > 0:
            await asyncio.sleep(d)
    def mark_success(self, ip: str):
        with self._lock:
            self._passed.add(ip)
    def reset(self, ip: str):
        with self._lock:
            self._passed.discard(ip)
            self._next.pop(ip, None)


_auth_gate = _AuthGate()


# ── camera-registry serialization guard ───────────────────────────────────────
# A camera entry in `_cameras` carries its working credential inline (`user`/`pass`,
# set by worker._new_cam) because every ONVIF/CGI call needs it. That is fine in
# memory and NOT fine anywhere the registry leaves the process: `data/events.json`
# and the `GET /api/status` body are both plain text an operator (or a proxy log, or
# a browser network tab) can read. Both used to emit the whole entry.
#
# `_CAM_PRIVATE_KEYS` is the single list of keys that must never cross that line —
# credentials plus the two bulky/internal fields the disk dump already skipped.
# Serialize a camera through `_public_cam(cam)` and new sensitive fields stay in
# by default rather than leaking until someone notices.
#
# `creds_tried` is kept: it is already masked at the point it is written
# (worker.py, `f"{user}/{'*'*len(pwd)}"`) and is the main clue for diagnosing an
# auth failure. It does disclose the password's length.
_CAM_PRIVATE_KEYS = frozenset({"user", "pass", "last_events", "_analytics_queried"})


def _public_cam(cam: dict) -> dict:
    """A shallow copy of one camera entry safe to write to disk or return over HTTP."""
    return {k: v for k, v in cam.items() if k not in _CAM_PRIVATE_KEYS}


def _public_cameras(cams: dict[str, dict]) -> dict[str, dict]:
    """`_public_cam` over the whole registry. Call under `_lock`."""
    return {ip: _public_cam(cam) for ip, cam in cams.items()}


# ── stato in memoria ──────────────────────────────────────────────────────────
_cameras: dict[str, dict] = {}
_event_log: list[dict]    = []
_alarms: dict[str, str]   = {}        # topic-level: {"Alarm uomo a terra": "on"}
_cam_alarms: dict[str, str] = {}      # per file/mqtt: {"STANZA_11": "on"}
_removed_ips: set[str]    = set()     # IP in fase di teardown (guardia transitoria)
# IPs the operator explicitly removed via the API during this process run. Distinct from
# the transient `_removed_ips` teardown guard: this one is consulted ONLY by the
# automatic periodic rescan, so a removal is not silently undone one interval later. A
# MANUAL rescan clears it (an explicit request for a full refresh), and saving/renaming
# a camera drops its IP from it.
_operator_removed: set[str] = set()
_worker_tasks: dict[str, "asyncio.Task"] = {}   # IP → task _camera_worker
_rule_tasks: dict[str, "asyncio.Task"]   = {}   # IP → task _rule_check_task
_active_pullpoints: dict[str, object]    = {}   # IP → live PullPoint service (for Unsubscribe on drop/shutdown)
_cgi_started: set[str]    = set()     # IP con thread CGI già avviato
_cgi_stop_events: dict[str, threading.Event] = {}   # IP → stop signal per attach-stream thread
_cgi_threads: dict[str, threading.Thread]    = {}   # IP → attach-stream thread
_keepalive_threads: dict[str, threading.Thread] = {}   # IP → fallback keepalive-probe thread
_cgi_responses: dict[str, object] = {}              # IP → in-flight requests.Response (to interrupt)
# Reentrant so a helper that itself takes _lock (e.g. mqtt._camera_working, the single
# source of truth for the confirmed-working predicate) can be called from within an
# already-locked section such as mqtt._refresh_detection_ok without deadlocking.
_lock = threading.RLock()
_main_loop: Optional[asyncio.AbstractEventLoop] = None


# ── auth-failure quarantine (per camera IP) ─────────────────────────────────────
# When a login fails with an AUTHENTICATION error (ONVIF credential rejected, or a
# Dahua CGI/HTTP 401/403) the IP is quarantined here and ALL its retry loops STOP,
# so a wrong-but-real password can never hammer the camera into the Dahua
# anti-intrusion lockout ("blocking the camera forever"). Distinct from a transient
# network error, which keeps its normal backoff/retry. Cleared on teardown/remove;
# otherwise sticky until restart (passwords are .env-sourced, so fixing one means
# editing .env and restarting — same recovery model as the placeholder guard).
# Guarded by _lock. Each entry: {"ip","name","source","detail","ts"}.
_auth_failed: dict[str, dict] = {}


def _mark_auth_failed(ip: str, source: str, detail: str, name: str = "") -> bool:
    """Quarantine an IP after an authentication failure. Returns True the FIRST time
    (so the caller logs the prominent warning once, not on every path/loop that also
    trips). Also flips the live camera row to the 'auth_failed' status. Thread-safe.
    The display name is taken from the live camera registry when not supplied."""
    with _lock:
        cam = _cameras.get(ip)
        disp = name or (cam.get("name") if cam else "") or ip
        first = ip not in _auth_failed
        _auth_failed[ip] = {
            "ip": ip, "name": disp, "source": source,
            "detail": detail, "ts": time.time(),
        }
        if cam is not None and not cam.get("simulated"):
            cam["status"] = "auth_failed"
            cam["error"]  = detail
    return first


def _is_auth_failed(ip: str) -> bool:
    with _lock:
        return ip in _auth_failed


def _clear_auth_failed(ip: str):
    """Drop an IP's quarantine (on teardown/remove) so a later re-add/rescan — after
    the operator has fixed .env and restarted — can retry it."""
    with _lock:
        _auth_failed.pop(ip, None)


def _reset_scan_auth_failures():
    """Clear only the scan-sourced quarantine entries. Called at the start of a manual
    rescan so the operator can refresh those warnings; camera-worker entries stay."""
    with _lock:
        for ip in [k for k, v in _auth_failed.items() if v.get("source") == "scan"]:
            _auth_failed.pop(ip, None)


def _auth_failures_list() -> list[dict]:
    """Snapshot of the current quarantine, sorted by IP (for /api/status)."""
    with _lock:
        return sorted((dict(v) for v in _auth_failed.values()), key=lambda e: e["ip"])


# ── hostname → last-resolved IP (RUNTIME ONLY, never persisted) ─────────────────
# A `cameras.list` entry may carry `hostname` instead of `ip`; the periodic
# resolution sweep matches the device-reported ONVIF hostname and records the IP it
# currently answers on here. `settings.yaml` keeps the hostname authoritative — the
# resolved address is deliberately NOT written back to it. Keyed by the canonical
# (trimmed + lowercased) hostname so a case difference between the config file and
# the device can never split one camera across two entries. Guarded by _lock.
# Each value is {"hostname": <as written in settings.yaml>, "ip": <resolved>} — the
# as-written spelling is kept so a diagnostic names the entry the way the operator
# will find it in the file, while every comparison uses the canonical key.
_hostname_ips: dict[str, dict] = {}


def _hostname_key(hostname) -> str:
    """Canonical key/comparison form of an ONVIF hostname: trimmed + lowercased.
    The single definition of "same hostname" shared by the resolver, the config
    helpers and this cache."""
    return str(hostname or "").strip().lower()


def _set_resolved_ip(hostname, ip: str):
    with _lock:
        _hostname_ips[_hostname_key(hostname)] = {
            "hostname": str(hostname or "").strip(), "ip": ip,
        }


def _resolved_ip(hostname) -> Optional[str]:
    """Last IP this hostname resolved to, or None if it has never resolved."""
    with _lock:
        e = _hostname_ips.get(_hostname_key(hostname))
        return e["ip"] if e else None


def _hostname_for_ip(ip: str) -> Optional[str]:
    """Reverse lookup: the configured hostname currently resolved to `ip` (spelled as
    in settings.yaml), or None when `ip` belongs to a static-`ip` (or unknown) camera.
    Every web API path addresses a camera by its runtime IP, so this is how a caller
    learns that the IP it was handed is really a hostname-configured entry."""
    with _lock:
        for key, e in _hostname_ips.items():
            if e["ip"] == ip:
                return e["hostname"] or key
    return None


def _drop_resolved_hostname(hostname) -> bool:
    """Forget a hostname's resolved IP (on removal). True if an entry was dropped."""
    with _lock:
        return _hostname_ips.pop(_hostname_key(hostname), None) is not None


def _rekey_resolved_hostname(old_hostname, new_hostname) -> bool:
    """Move a cached resolved IP from `old_hostname` to `new_hostname`, leaving no
    entry under the old key. Used by the rename path: renaming a camera sets its
    ONVIF hostname, so the cache key changes while the IP does not — a stale key
    would make the next sweep treat the camera as never-resolved and spawn a second
    worker on the IP that already has one. True if a cached IP was moved."""
    with _lock:
        old_k, new_k = _hostname_key(old_hostname), _hostname_key(new_hostname)
        e = _hostname_ips.pop(old_k, None)
        if e is None:
            return False
        _hostname_ips[new_k] = {"hostname": str(new_hostname or "").strip(), "ip": e["ip"]}
        return True


def _resolved_hostnames() -> dict[str, str]:
    """Snapshot of the canonical hostname → resolved-IP map."""
    with _lock:
        return {k: e["ip"] for k, e in _hostname_ips.items()}
