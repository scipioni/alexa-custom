"""Lightweight runtime metrics for the daemon.

A process-wide, thread-safe registry of counters, gauges, and simple timing
summaries. Designed to be import-cheap and dependency-free so any module can
record without coupling: ``from alexa_custom import metrics`` then
``metrics.inc("wake_detections")``.

The web dashboard exposes a snapshot at ``/metrics`` and a liveness view at
``/health``. There is no time-series storage — this is for at-a-glance health
of a single always-on device, not a Prometheus replacement.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

_lock = threading.Lock()
_counters: dict[str, float] = {}
_gauges: dict[str, float] = {}


@dataclass
class _Timing:
    count: int = 0
    total: float = 0.0
    last: float = 0.0
    max: float = 0.0


_timings: dict[str, _Timing] = {}

# Wall-clock start, for uptime. (Plain time.time() — fine in normal code.)
_start_time = time.time()


def inc(name: str, amount: float = 1.0) -> None:
    """Increment a monotonic counter (e.g. wake_detections, mqtt_reconnects)."""
    with _lock:
        _counters[name] = _counters.get(name, 0.0) + amount


def set_gauge(name: str, value: float) -> None:
    """Set a point-in-time value (e.g. audio_connected, queue_depth)."""
    with _lock:
        _gauges[name] = value


def observe(name: str, value: float) -> None:
    """Record a sample for a timing/size summary (count, total, last, max)."""
    with _lock:
        t = _timings.get(name)
        if t is None:
            t = _Timing()
            _timings[name] = t
        t.count += 1
        t.total += value
        t.last = value
        if value > t.max:
            t.max = value


@dataclass
class _Timer:
    """Context manager that records elapsed seconds into a timing summary."""

    name: str
    _t0: float = field(default=0.0)

    def __enter__(self) -> _Timer:
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc) -> None:
        observe(self.name, time.monotonic() - self._t0)


def timer(name: str) -> _Timer:
    """`with metrics.timer("stt_latency_s"): ...` records the block's duration."""
    return _Timer(name)


def uptime_s() -> float:
    return time.time() - _start_time


def snapshot() -> dict:
    """Return a JSON-serialisable view of all metrics."""
    with _lock:
        timings = {
            name: {
                "count": t.count,
                "total": round(t.total, 6),
                "last": round(t.last, 6),
                "max": round(t.max, 6),
                "avg": round(t.total / t.count, 6) if t.count else 0.0,
            }
            for name, t in _timings.items()
        }
        return {
            "uptime_s": round(uptime_s(), 1),
            "counters": dict(_counters),
            "gauges": dict(_gauges),
            "timings": timings,
        }


def reset() -> None:
    """Clear all metrics — intended for tests."""
    global _start_time
    with _lock:
        _counters.clear()
        _gauges.clear()
        _timings.clear()
        _start_time = time.time()
