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
    0: "◎",
    1: "🎤",
    2: "📝",
    3: "⏳",
    4: "🔊",
    5: "📞",
    6: "✕",
    7: "🔗",
    8: "⬛",
}

_LED_BASE = "/sys/class/leds"
_LED_NAMES = ("red", "green", "blue")

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


# ── Bridge RPC backend (matrix + MCU LEDs) ────────────────────────────


class BridgeDisplay(DisplayBackend):

    def __init__(self) -> None:
        from arduino.app_utils import Bridge
        self._bridge = Bridge
        self._bridge.call("ping")

    def show(self, state: str) -> None:
        icon_id = STATE_ICONS.get(state, 8)
        color = STATE_COLORS.get(state, (0, 0, 0))
        try:
            self._bridge.call("set_matrix_icon", icon_id)
            self._bridge.call("set_leds", color[0], color[1], color[2],
                              color[0], color[1], color[2])
        except Exception:
            logger.warning("[display] Bridge call failed", exc_info=True)

    def clear(self) -> None:
        try:
            self._bridge.call("clear")
        except Exception:
            pass


# ── Factory ───────────────────────────────────────────────────────────


def get_display_backend(backend: str = "auto") -> DisplayBackend:

    if backend == "mock":
        return MockDisplay()

    if backend in ("bridge", "auto"):
        try:
            return BridgeDisplay()
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
