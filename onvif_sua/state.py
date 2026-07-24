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
# ── stato in memoria ──────────────────────────────────────────────────────────
_cameras: dict[str, dict] = {}
_event_log: list[dict]    = []
_alarms: dict[str, str]   = {}        # topic-level: {"Alarm uomo a terra": "on"}
_cam_alarms: dict[str, str] = {}      # per file/mqtt: {"STANZA_11": "on"}
_removed_ips: set[str]    = set()     # IP in fase di teardown (guardia transitoria)
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
