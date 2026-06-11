from __future__ import annotations

import abc
import logging
import os
import queue
import threading
import time

logger = logging.getLogger(__name__)

# ── State → color mapping ─────────────────────────────────────────────

STATE_COLORS: dict[str, tuple[int, int, int]] = {
    "idle":          (0, 0, 255),    # blue
    "listening":     (0, 255, 0),    # green
    "wake":          (0, 255, 0),    # green
    "transcribing":  (0, 255, 0),    # green
    "llm_thinking":  (255, 255, 0),  # yellow
    "llm_reply":     (255, 0, 0),    # red
    "speaking":      (255, 0, 0),    # red
    "gated":         (128, 0, 128),  # purple
    "nomatch":       (255, 0, 0),    # red (flash)
    "connected":     (0, 255, 255),  # cyan
    "disconnected":  (0, 0, 0),      # off
    "starting":      (255, 165, 0),  # orange
}

STATE_ICONS: dict[str, int] = {
    "idle":          0,
    "listening":     1,
    "wake":          1,
    "transcribing":  2,
    "llm_thinking":  3,
    "llm_reply":     4,
    "speaking":      4,
    "gated":         5,
    "nomatch":       6,
    "connected":     7,
    "disconnected":  8,
    "starting":      7,
}

_MATRIX_CHARS: dict[int, str] = {
    0: "\u25ce",
    1: "\U0001f3a4",
    2: "\U0001f4dd",
    3: "\u23f3",
    4: "\U0001f50a",
    5: "\U0001f4de",
    6: "\u2715",
    7: "\U0001f517",
    8: "\u2b1b",
}

_LED_BASE = "/sys/class/leds"

_MPU_LED_MAP = {
    "red":   ("red", "user"),
    "green": ("green", "user"),
    "blue":  ("blue", "user"),
}


def _color_to_sysfs(r: int, g: int, b: int) -> dict[str, int]:
    return {"red": 1 if r > 0 else 0, "green": 1 if g > 0 else 0, "blue": 1 if b > 0 else 0}


# ── Abstract backend ──────────────────────────────────────────────────


class DisplayBackend(abc.ABC):

    @abc.abstractmethod
    def show(self, state: str) -> None:
        ...

    @abc.abstractmethod
    def clear(self) -> None:
        ...


# ── Mock backend (PC / fallback) ──────────────────────────────────────


class MockDisplay(DisplayBackend):

    def show(self, state: str) -> None:
        color = STATE_COLORS.get(state, (0, 0, 0))
        icon = _MATRIX_CHARS.get(STATE_ICONS.get(state, 8), "?")
        logger.info(
            "[display] %s | color=(%d,%d,%d) | icon=%s",
            state, color[0], color[1], color[2], icon,
        )

    def clear(self) -> None:
        logger.info("[display] clear")


# ── GPIO sysfs backend (MPU LEDs only) ────────────────────────────────


class GpioLedDisplay(DisplayBackend):

    def __init__(self) -> None:
        self._led_base = _LED_BASE

    def _write_led(self, color: str, value: int) -> None:
        ns, sub = _MPU_LED_MAP[color]
        path = f"{self._led_base}/{ns}:{sub}/brightness"
        try:
            with open(path, "w") as f:
                f.write(f"{value}\n")
        except OSError:
            pass

    def _set_color(self, r: int, g: int, b: int) -> None:
        channels = _color_to_sysfs(r, g, b)
        for color, value in channels.items():
            self._write_led(color, value)

    def show(self, state: str) -> None:
        color = STATE_COLORS.get(state, (0, 0, 0))
        self._set_color(*color)

    def clear(self) -> None:
        self._set_color(0, 0, 0)


# ── Bridge RPC backend ────────────────────────────────────────────────
# Connects to the arduino-router on the UNO Q via TCP (port 7501).
# Router protocol: [0, msg_id, "method", [args]] / [1, msg_id, err, result]
# The STM32 firmware uses Arduino_RouterBridge to register methods.

import os

_ROUTER_HOST = os.environ.get("ALEXA_DISPLAY_HOST", "192.168.9.43")
_ROUTER_PORT = int(os.environ.get("ALEXA_DISPLAY_PORT", "7501"))


class _BridgeClient:

    def __init__(self, host: str = _ROUTER_HOST, port: int = _ROUTER_PORT) -> None:
        import msgpack as _mp
        self._host = host
        self._port = port
        self._sock = self._connect()
        self._lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, object] = {}
        self._next_id = 0
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()

    def _connect(self):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((self._host, self._port))
        s.settimeout(0.05)
        return s

    def _handle_response(self, obj: list) -> None:
        _typ, msg_id, err, result = (obj + [None, None, None])[:4]
        if msg_id in self._pending:
            self._responses[msg_id] = (err, result)
            self._pending[msg_id].set()

    def _reader_loop(self) -> None:
        import msgpack as _mp
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(4096)
            except (BlockingIOError, ConnectionError, OSError):
                time.sleep(0.05)
                continue
            except Exception as e:
                logger.debug("[display] Socket read error: %s", e)
                time.sleep(0.1)
                continue
            if chunk:
                buf.extend(chunk)
            self._try_parse(buf)

    def _try_parse(self, buf: bytearray) -> None:
        import msgpack as _mp
        offset = 0
        while offset < len(buf):
            try:
                obj, used = _mp.unpackb(
                    bytes(buf[offset:]), raw=False, strict_map_key=False
                )
            except (_mp.UnpackValueError, _mp.ExtraData):
                offset += 1
                continue
            except Exception:
                break
            if isinstance(obj, list) and len(obj) >= 3 and obj[0] == 1:
                self._handle_response(obj)
            offset += used
        if offset > 0:
            del buf[:offset]

    def call(self, method: str, *args: int) -> bool:
        import msgpack
        mid = self._next_id
        self._next_id += 1
        ev = threading.Event()
        self._pending[mid] = ev
        body = msgpack.packb([0, mid, method, list(args)])
        with self._lock:
            try:
                self._sock.sendall(body)
            except Exception:
                self._sock = self._connect()
                self._sock.sendall(body)
        got = ev.wait(timeout=5.0)
        self._pending.pop(mid, None)
        if not got:
            logger.warning("[display] RPC timeout: %s (msg_id=%d)", method, mid)
            return False
        err, result = self._responses.pop(mid, (None, None))
        return err is None and result is not False

    def ping(self) -> bool:
        return self.call("ping")

    def set_text(self, text: str) -> bool:
        return self.call("set_text", text)

    def set_leds(self,
                 r: int, g: int, b: int,
                 r1: int, g1: int, b1: int) -> bool:
        return self.call("set_leds", r, g, b, r1, g1, b1)

    def clear(self) -> bool:
        return self.call("clear")

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except Exception:
            pass


class BridgeDisplay(DisplayBackend):

    def __init__(self, host: str = _ROUTER_HOST, port: int = _ROUTER_PORT) -> None:
        self._client = _BridgeClient(host, port)
        self._client.ping()

    def show(self, state: str) -> None:
        color = STATE_COLORS.get(state, (0, 0, 0))
        text = state.upper()
        try:
            ok1 = self._client.set_text(text)
            ok2 = self._client.set_leds(
                color[0], color[1], color[2],
                color[0], color[1], color[2],
            )
            if not ok1 or not ok2:
                logger.warning("[display] RPC call returned False")
        except Exception:
            logger.warning("[display] Bridge call failed", exc_info=True)

    def clear(self) -> None:
        try:
            self._client.clear()
        except Exception:
            pass


# ── Factory ───────────────────────────────────────────────────────────


def get_display_backend(backend: str = "auto") -> DisplayBackend:

    if backend == "mock":
        return MockDisplay()

    if backend in ("bridge", "auto"):
        try:
            host = os.environ.get("ALEXA_DISPLAY_HOST", _ROUTER_HOST)
            port = int(os.environ.get("ALEXA_DISPLAY_PORT", str(_ROUTER_PORT)))
            return BridgeDisplay(host, port)
        except Exception:
            if backend == "bridge":
                logger.warning(
                    "[display] Bridge backend unavailable — falling back"
                )

    if backend in ("gpio", "auto"):
        led_path = f"{_LED_BASE}/red:user/brightness"
        if os.path.isfile(led_path):
            try:
                display = GpioLedDisplay()
                display._set_color(0, 0, 255)
                time.sleep(0.05)
                display._set_color(0, 0, 0)
                return display
            except Exception:
                if backend == "gpio":
                    logger.warning(
                        "[display] GPIO backend unavailable — falling back"
                    )
        elif backend == "gpio":
            logger.warning(
                "[display] GPIO backend unavailable (no sysfs LEDs) — falling back"
            )

    return MockDisplay()


# ── DisplayController ─────────────────────────────────────────────────


class DisplayController:

    def __init__(self, backend: DisplayBackend) -> None:
        self._backend = backend
        self._queue: queue.Queue = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="display")
        self._thread.start()

    def on_event(self, event: str, data: dict) -> None:
        self._queue.put(("event", event, data))

    def on_stt_event(self, event: str, data: dict) -> None:
        self._queue.put(("stt", event, data))

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(("stop", None, None))

    def _run(self) -> None:
        current_state = "idle"
        self._backend.show(current_state)
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if msg[0] == "stop":
                break

            next_state = self._resolve_state(msg)
            if next_state is not None and next_state != current_state:
                current_state = next_state
                self._backend.show(current_state)

        self._backend.clear()

    def _resolve_state(
        self, msg: tuple[str, str, dict]
    ) -> str | None:
        kind, event, data = msg

        if kind == "event":
            if event in ("starting", "connected", "disconnected"):
                return event
            if event == "idle":
                return "idle"
            return None

        if kind == "stt":
            if event == "level":
                return None
            if event in ("listening", "wake"):
                return "wake"
            if event == "transcribing":
                return event
            if event == "llm_thinking":
                return event
            if event in ("llm_reply", "llm_unreachable"):
                return "llm_reply"
            if event in ("matched",):
                return "speaking"
            if event in ("nomatch",):
                return "nomatch"
            if event == "gated":
                return event
            if event == "idle":
                return event

        return None
