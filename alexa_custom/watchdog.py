"""Systemd watchdog integration via sd_notify()."""

import ctypes
import logging
import os

logger = logging.getLogger(__name__)

# Load libsystemd for sd_notify() — libc.so.6 on aarch64 often lacks it
_lib = None
for lib in ("libsystemd.so.0", "libsystemd.so", "libc.so.6"):
    try:
        _lib = ctypes.CDLL(lib)
        break
    except OSError:
        pass


def sd_notify(state: str) -> bool:
    """Send a notification to systemd via sd_notify().

    Used with Type=notify systemd services to implement the watchdog
    mechanism. Call periodically (e.g., every 10 seconds) when the daemon
    is healthy; systemd will restart the service if it doesn't receive
    a notification within the WatchdogSec timeout.

    Returns True if the notification was sent (systemd socket exists),
    False otherwise (not running under systemd or notification failed).
    """
    if not _lib:
        return False

    # sd_notify() only works if NOTIFY_SOCKET is set (systemd passes this)
    if not os.environ.get("NOTIFY_SOCKET"):
        return False

    state_bytes = state.encode("utf-8")
    try:
        # int sd_notify(int unset_environment, const char *state)
        # Return value: 0 if no NOTIFY_SOCKET, >0 if sent, <0 on error
        result = _lib.sd_notify(ctypes.c_int(0), ctypes.c_char_p(state_bytes))
        if result > 0:
            logger.debug(f"sd_notify({state!r}) sent successfully")
            return True
        elif result == 0:
            logger.debug("sd_notify() not available (no NOTIFY_SOCKET)")
            return False
        else:
            logger.warning(f"sd_notify({state!r}) error: {result}")
            return False
    except Exception as e:
        logger.warning(f"sd_notify() call failed: {e}")
        return False


def should_use_watchdog() -> bool:
    """Return True if running under systemd with a watchdog configured."""
    return "WATCHDOG_USEC" in os.environ
