"""Tests for STT heartbeat + watchdog ping gating (tasks 3.1-3.5) and
shutdown-responsive sleeps (task 4.2)."""

import threading
import time

from alexa_custom.client import _stt_heartbeat_fresh
from alexa_custom.stt import _stt_heartbeat


class TestSttHeartbeatHolder:
    def test_heartbeat_is_mutable_list(self):
        """_stt_heartbeat is a single-element mutable list (GIL-safe swap)."""
        assert isinstance(_stt_heartbeat, list)
        assert len(_stt_heartbeat) == 1

    def test_heartbeat_can_be_stamped(self):
        old = _stt_heartbeat[0]
        _stt_heartbeat[0] = time.monotonic()
        assert _stt_heartbeat[0] >= old


class TestWatchdogPingGating:
    def test_fresh_heartbeat_allows_ping(self):
        """When the STT stamp is recent, _stt_heartbeat_fresh returns True."""
        ref: list[float] = [time.monotonic()]
        freshness = 20.0
        assert _stt_heartbeat_fresh(ref, freshness) is True

    def test_stale_heartbeat_withholds_ping(self):
        """When the STT stamp is older than freshness, returns False."""
        ref: list[float] = [time.monotonic() - 30.0]  # 30s ago
        freshness = 20.0
        assert _stt_heartbeat_fresh(ref, freshness) is False

    def test_no_stt_always_allows_ping(self):
        """When stt_heartbeat_ref is None (no STT), ping is always allowed."""
        assert _stt_heartbeat_fresh(None, 20.0) is True

    def test_zero_freshness_always_allows_ping(self):
        """When freshness == 0 (watchdog_sec <= ping_interval), gate is disabled."""
        stale_ref: list[float] = [time.monotonic() - 999.0]
        assert _stt_heartbeat_fresh(stale_ref, 0.0) is True

    def test_negative_freshness_always_allows_ping(self):
        """Negative freshness (watchdog_sec < ping_interval) disables gate."""
        stale_ref: list[float] = [time.monotonic() - 999.0]
        assert _stt_heartbeat_fresh(stale_ref, -5.0) is True

    def test_boundary_exactly_at_freshness_is_stale(self):
        """A stamp exactly `freshness` seconds old is considered stale."""
        freshness = 20.0
        ref: list[float] = [time.monotonic() - freshness]
        # age == freshness → not < freshness → stale
        assert _stt_heartbeat_fresh(ref, freshness) is False


class TestShutdownResponsiveSleep:
    def test_stop_event_interrupts_backend_reload_wait(self):
        """stop_event.wait(2) exits promptly when the event is set during the wait."""
        stop_event = threading.Event()
        elapsed_times: list[float] = []

        def _waiter():
            t0 = time.monotonic()
            stop_event.wait(2)  # mirrors the reload-error backoff in run_stt_worker
            elapsed_times.append(time.monotonic() - t0)

        t = threading.Thread(target=_waiter)
        t.start()
        time.sleep(0.05)  # let the waiter reach wait()
        stop_event.set()
        t.join(timeout=1.0)

        assert not t.is_alive(), "waiter thread did not exit promptly"
        assert elapsed_times[0] < 0.5, (
            f"Expected <0.5s after stop_event.set(), got {elapsed_times[0]:.2f}s"
        )
