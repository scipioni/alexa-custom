from __future__ import annotations

import abc
import importlib
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── State → color mapping ─────────────────────────────────────────────

STATE_COLORS: dict[str, tuple[int, int, int]] = {
    "idle": (0, 0, 255),  # blue
    "listening": (0, 255, 0),  # green
    "wake": (0, 255, 0),  # green
    "transcribing": (0, 255, 0),  # green
    "llm_thinking": (255, 255, 0),  # yellow
    "llm_reply": (255, 0, 0),  # red
    "speaking": (255, 0, 0),  # red
    "gated": (128, 0, 128),  # purple
    "nomatch": (255, 0, 0),  # red (flash)
    "connected": (0, 255, 255),  # cyan
    "disconnected": (0, 0, 0),  # off
    "starting": (255, 165, 0),  # orange
}

STATE_ICONS: dict[str, int] = {
    "idle": 0,
    "listening": 1,
    "wake": 1,
    "transcribing": 2,
    "llm_thinking": 3,
    "llm_reply": 4,
    "speaking": 4,
    "gated": 5,
    "nomatch": 6,
    "connected": 7,
    "disconnected": 8,
    "starting": 7,
}

STATE_SHORT: dict[str, str] = {
    "idle": "ID",
    "listening": "LI",
    "wake": "WK",
    "transcribing": "TR",
    "llm_thinking": "TH",
    "llm_reply": "RP",
    "speaking": "SP",
    "gated": "GT",
    "nomatch": "NO",
    "connected": "CO",
    "disconnected": "DI",
    "starting": "ST",
}

STATE_ICON_IDS: dict[str, int] = {
    "idle": 0,
    "listening": 1,
    "wake": 1,
    "transcribing": 1,
    "llm_thinking": 2,
    "llm_reply": 3,
    "speaking": 3,
    "gated": 7,
    "nomatch": 4,
    "connected": 5,
    "disconnected": 6,
    "starting": 8,
}

STATE_TEXTS: dict[str, str] = {
    "idle": "in ascolto",
    "listening": "ascolto...",
    "wake": "parla pure",
    "transcribing": "trascrivo...",
    "llm_thinking": "sto pensando",
    "llm_reply": "rispondo...",
    "speaking": "sto parlando",
    "gated": "in chiamata",
    "nomatch": "non ho capito",
    "connected": "connesso",
    "disconnected": "disconnesso",
    "starting": "avvio...",
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
    "red": ("red", "user"),
    "green": ("green", "user"),
    "blue": ("blue", "user"),
}


def _color_to_sysfs(r: int, g: int, b: int) -> dict[str, int]:
    return {
        "red": 1 if r > 0 else 0,
        "green": 1 if g > 0 else 0,
        "blue": 1 if b > 0 else 0,
    }


# ── Abstract backend ──────────────────────────────────────────────────


class DisplayBackend(abc.ABC):
    @abc.abstractmethod
    def show(self, state: str) -> None: ...

    @abc.abstractmethod
    def clear(self) -> None: ...


# ── Mock backend (PC / fallback) ──────────────────────────────────────


class MockDisplay(DisplayBackend):
    def show(self, state: str) -> None:
        color = STATE_COLORS.get(state, (0, 0, 0))
        icon = _MATRIX_CHARS.get(STATE_ICONS.get(state, 8), "?")
        logger.info(
            "[display] %s | color=(%d,%d,%d) | icon=%s",
            state,
            color[0],
            color[1],
            color[2],
            icon,
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
# Communicates with the STM32 firmware via MsgPack RPC.
# Transport: TCP (arduino-router on port 7501) or subprocess (uart_bridge).
# Protocol: [0, msg_id, "method", [args]] / [1, msg_id, err, result]

_BRIDGE_CMD_DEFAULT = os.environ.get("ALEXA_DISPLAY_CMD", "uart_bridge")
_ROUTER_HOST = os.environ.get("ALEXA_DISPLAY_HOST", "127.0.0.1")
_ROUTER_PORT = int(os.environ.get("ALEXA_DISPLAY_PORT", "7501"))
_ROUTER_UNIX_SOCKET = os.environ.get(
    "ALEXA_DISPLAY_UNIX_SOCKET", "/var/run/arduino-router.sock"
)
_BRIDGE_TRANSPORT = os.environ.get("ALEXA_DISPLAY_TRANSPORT", "auto")


class _BridgeClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        cmd: str | None = None,
        unix_socket: str | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, object] = {}
        self._next_id = 0
        self._stop = threading.Event()
        self._sock: Any = None
        self._proc: subprocess.Popen | None = None
        self._unix_socket = unix_socket or _ROUTER_UNIX_SOCKET

        if cmd:
            logger.debug("[display] Bridge subprocess: %s", cmd)
            self._proc = subprocess.Popen(
                cmd.split(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        else:
            import socket

            if self._unix_socket and os.path.exists(self._unix_socket):
                h = None
                p = None
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.settimeout(5.0)
                self._sock.connect(self._unix_socket)
            else:
                h = host or _ROUTER_HOST
                p = port or _ROUTER_PORT
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(5.0)
                self._sock.connect((h, p))
            self._sock.settimeout(0.05)

        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()

    def _read(self, n: int) -> bytes:
        if self._proc:
            return os.read(self._proc.stdout.fileno(), n)
        return self._sock.recv(n)

    def _write(self, data: bytes) -> None:
        if self._proc:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        else:
            self._sock.sendall(data)

    def _reconnect(self) -> None:
        if self._proc:
            return
        import socket

        if self._unix_socket and os.path.exists(self._unix_socket):
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(5.0)
            self._sock.connect(self._unix_socket)
        else:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(5.0)
            self._sock.connect((_ROUTER_HOST, _ROUTER_PORT))
        self._sock.settimeout(0.05)

    def _handle_response(self, obj: list) -> None:
        _typ, msg_id, err, result = (obj + [None, None, None])[:4]
        if msg_id in self._pending:
            self._responses[msg_id] = (err, result)
            self._pending[msg_id].set()

    def _reader_loop(self) -> None:
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = self._read(4096)
            except (BlockingIOError, OSError):
                time.sleep(0.05)
                continue
            except Exception as e:
                logger.debug("[display] Bridge read error: %s", e)
                time.sleep(0.1)
                continue
            if chunk:
                buf.extend(chunk)
            self._try_parse(buf)

    def _try_parse(self, buf: bytearray) -> None:
        import msgpack

        if not buf:
            return
        unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        unpacker.feed(bytes(buf))
        consumed = 0
        try:
            for obj in unpacker:
                consumed = unpacker.tell()
                if isinstance(obj, list) and len(obj) >= 3 and obj[0] == 1:
                    self._handle_response(obj)
        except (msgpack.UnpackValueError, msgpack.OutOfData):
            pass
        except Exception:
            pass
        if consumed > 0:
            del buf[:consumed]

    def call(self, method: str, *args: Any) -> bool:
        import msgpack

        mid = self._next_id
        self._next_id += 1
        ev = threading.Event()
        self._pending[mid] = ev
        body = msgpack.packb([0, mid, method, list(args)])
        with self._lock:
            try:
                self._write(body)
            except Exception:
                if not self._proc:
                    self._reconnect()
                    self._write(body)
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

    def set_leds(self, r: int, g: int, b: int, r1: int, g1: int, b1: int) -> bool:
        return self.call("set_leds", r, g, b, r1, g1, b1)

    def clear(self) -> bool:
        return self.call("clear")

    def close(self) -> None:
        self._stop.set()
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        elif self._sock:
            try:
                self._sock.close()
            except Exception:
                pass


class BridgeDisplay(DisplayBackend):
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        cmd: str | None = None,
        unix_socket: str | None = None,
    ) -> None:
        self._client = _BridgeClient(
            host=host, port=port, cmd=cmd, unix_socket=unix_socket
        )
        if not self._client.ping():
            raise RuntimeError("Bridge ping failed")

    def show(self, state: str) -> None:
        color = STATE_COLORS.get(state, (0, 0, 0))
        icon_id = STATE_ICON_IDS.get(state, 0)
        try:
            ok1 = self._client.call("set_icon", icon_id)
            ok2 = self._client.set_leds(
                color[0],
                color[1],
                color[2],
                color[0],
                color[1],
                color[2],
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


# ── I²C SSD1306 OLED driver ──────────────────────────────────────────


class _Ssd1306:
    def __init__(
        self, bus: int = 1, addr: int = 0x3C, width: int = 128, height: int = 64
    ):
        import smbus2

        self._i2c = smbus2.SMBus(bus)
        self._addr = addr
        self._width = width
        self._height = height
        self._pages = height // 8
        self._buffer = bytearray(width * self._pages)
        self._init_display()
        self.clear()

    @staticmethod
    def _make_cmds(*cmds: int) -> bytes:
        return b"\x00" + bytes(cmds)

    def _write_cmd(self, cmd: int) -> None:
        self._i2c.write_byte_data(self._addr, 0x00, cmd)

    def _write_cmds(self, *cmds: int) -> None:
        for cmd in cmds:
            self._write_cmd(cmd)

    def _write_data(self, data: bytes) -> None:
        from smbus2 import i2c_msg

        msg = i2c_msg.write(self._addr, b"\x40" + data)
        self._i2c.i2c_rdwr(msg)

    def _init_display(self) -> None:
        self._write_cmds(
            0xAE,
            0xD5,
            0x80,
            0xA8,
            0x3F,
            0xD3,
            0x00,
            0x40,
            0x8D,
            0x14,
            0x20,
            0x00,
            0xA1,
            0xC8,
            0xDA,
            0x12,
            0x81,
            0xCF,
            0xD9,
            0xF1,
            0xDB,
            0x40,
            0xA4,
            0xA6,
            0x2E,
            0xAF,
        )

    def clear(self) -> None:
        self._buffer = bytearray(self._width * self._pages)

    def _set_pixel(self, x: int, y: int, on: bool = True) -> None:
        if 0 <= x < self._width and 0 <= y < self._height:
            idx = x + (y // 8) * self._width
            bit = 1 << (y & 7)
            if on:
                self._buffer[idx] |= bit
            else:
                self._buffer[idx] &= ~bit

    def _draw_char(self, col: int, row: int, ch: str, on: bool = True) -> int:
        from alexa_custom.display_fonts import FONT5X7

        code = ord(ch)
        if code < 0x20 or code > 0x7E:
            return col + 6
        idx = (code - 0x20) * 5
        y0 = row * 8
        for c in range(5):
            byte_val = FONT5X7[idx + c]
            for r in range(7):
                if byte_val & (1 << r):
                    self._set_pixel(col + c, y0 + r, on)
        return col + 6

    def draw_text(self, x: int, y: int, text: str, on: bool = True) -> None:
        col = x
        row = y
        for ch in text:
            if ch == "\n":
                col = x
                row += 1
            else:
                col = self._draw_char(col, row, ch, on)
                if col + 5 > self._width:
                    col = x
                    row += 1

    def draw_progress(self, fraction: float) -> None:
        bar_width = self._width - 8
        fill = int(bar_width * max(0.0, min(1.0, fraction)))
        y = self._height - 12
        for x in range(bar_width):
            on = x < fill
            self._set_pixel(4 + x, y, on)
            self._set_pixel(4 + x, y + 1, on)

    def contrast(self, value: int) -> None:
        self._write_cmds(0x81, max(0, min(255, value)))

    def flush(self) -> None:
        for page in range(self._pages):
            col_start = 0
            col_end = self._width - 1
            self._write_cmds(0x21, col_start, col_end, 0x22, page, page)
            start = page * self._width
            self._write_data(bytes(self._buffer[start : start + self._width]))


# ── I²C OLED display backend ──────────────────────────────────────────

_I2C_DEFAULT_BUS = int(os.environ.get("ALEXA_DISPLAY_I2C_BUS", "1"))
_I2C_DEFAULT_ADDR = int(os.environ.get("ALEXA_DISPLAY_I2C_ADDR", "0x3C"), 16)
_I2C_DEFAULT_WIDTH = int(os.environ.get("ALEXA_DISPLAY_I2C_WIDTH", "128"))
_I2C_DEFAULT_HEIGHT = int(os.environ.get("ALEXA_DISPLAY_I2C_HEIGHT", "64"))


class I2cOledDisplay(DisplayBackend):
    def __init__(
        self,
        bus: int = _I2C_DEFAULT_BUS,
        addr: int = _I2C_DEFAULT_ADDR,
        width: int = _I2C_DEFAULT_WIDTH,
        height: int = _I2C_DEFAULT_HEIGHT,
    ):
        self._bus = bus
        self._addr = addr
        self._width = width
        self._height = height
        self._oled = _Ssd1306(bus, addr, width, height)

    def show(self, state: str) -> None:
        self._oled.clear()
        label = state.upper()
        desc = STATE_TEXTS.get(state, "")
        cx = self._width // 2
        label_x = cx - (len(label) * 6) // 2
        self._oled.draw_text(label_x, 1, label)
        if desc:
            desc_x = cx - (len(desc) * 6) // 2
            self._oled.draw_text(desc_x, 3, desc)
        self._oled.draw_progress(
            0.3
            if state == "listening"
            else 0.5
            if state in ("wake", "transcribing")
            else 0.7
            if state in ("llm_thinking", "speaking", "llm_reply")
            else 0.0
        )
        footer = "alexa-custom"
        fx = cx - (len(footer) * 6) // 2
        self._oled.draw_text(fx, 6, footer)
        self._oled.flush()

    def clear(self) -> None:
        self._oled.clear()
        self._oled.flush()


# ── Factory ───────────────────────────────────────────────────────────


def get_display_backend(
    backend: str = "auto", transport: str = "auto"
) -> DisplayBackend:

    if backend == "mock":
        return MockDisplay()

    if backend in ("bridge", "auto"):
        transport = os.environ.get("ALEXA_DISPLAY_TRANSPORT", _BRIDGE_TRANSPORT)

        if transport == "subprocess":
            cmd = os.environ.get("ALEXA_DISPLAY_CMD", _BRIDGE_CMD_DEFAULT)
            if shutil.which(cmd.split()[0]) if " " in cmd else shutil.which(cmd):
                try:
                    logger.debug("[display] Bridge subprocess: %s", cmd)
                    return BridgeDisplay(cmd=cmd)
                except Exception:
                    logger.warning("[display] Bridge subprocess unavailable")
            else:
                logger.warning("[display] Bridge command not found: %s", cmd)
            return MockDisplay()

        if transport == "unix":
            unix_sock = os.environ.get("ALEXA_DISPLAY_UNIX_SOCKET", _ROUTER_UNIX_SOCKET)
            if os.path.exists(unix_sock):
                try:
                    logger.debug("[display] Bridge Unix socket: %s", unix_sock)
                    return BridgeDisplay(unix_socket=unix_sock)
                except Exception:
                    logger.warning("[display] Bridge Unix socket unavailable")
            else:
                logger.warning("[display] Bridge Unix socket not found: %s", unix_sock)
            return MockDisplay()

        if transport == "tcp":
            host = os.environ.get("ALEXA_DISPLAY_HOST", _ROUTER_HOST)
            port = int(os.environ.get("ALEXA_DISPLAY_PORT", str(_ROUTER_PORT)))
            try:
                logger.debug("[display] Bridge TCP: %s:%d", host, port)
                return BridgeDisplay(host=host, port=port)
            except Exception:
                logger.warning("[display] Bridge TCP unavailable")
            return MockDisplay()

        cmd = os.environ.get("ALEXA_DISPLAY_CMD", _BRIDGE_CMD_DEFAULT)
        if shutil.which(cmd.split()[0]) if " " in cmd else shutil.which(cmd):
            try:
                logger.debug("[display] Trying bridge subprocess: %s", cmd)
                return BridgeDisplay(cmd=cmd)
            except Exception:
                if backend == "bridge":
                    logger.warning(
                        "[display] Bridge subprocess unavailable — trying Unix socket"
                    )

        unix_sock = os.environ.get("ALEXA_DISPLAY_UNIX_SOCKET", _ROUTER_UNIX_SOCKET)
        if os.path.exists(unix_sock):
            try:
                logger.debug("[display] Trying bridge Unix socket: %s", unix_sock)
                return BridgeDisplay(unix_socket=unix_sock)
            except Exception:
                if backend == "bridge":
                    logger.warning(
                        "[display] Bridge Unix socket unavailable — trying TCP"
                    )

        try:
            host = os.environ.get("ALEXA_DISPLAY_HOST", _ROUTER_HOST)
            port = int(os.environ.get("ALEXA_DISPLAY_PORT", str(_ROUTER_PORT)))
            return BridgeDisplay(host=host, port=port)
        except Exception:
            if backend == "bridge":
                logger.warning("[display] Bridge TCP unavailable — falling back")

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
                    logger.warning("[display] GPIO backend unavailable — falling back")
        elif backend == "gpio":
            logger.warning(
                "[display] GPIO backend unavailable (no sysfs LEDs) — falling back"
            )

    if backend in ("i2c", "auto"):
        try:
            importlib.import_module("smbus2")
            bus = _I2C_DEFAULT_BUS
            addr = _I2C_DEFAULT_ADDR
            width = _I2C_DEFAULT_WIDTH
            height = _I2C_DEFAULT_HEIGHT

            display = I2cOledDisplay(bus, addr, width, height)
            display.clear()
            logger.info(
                "[display] I²C OLED ready (bus=%d addr=0x%02x %dx%d)",
                bus,
                addr,
                width,
                height,
            )
            return display
        except ImportError:
            if backend == "i2c":
                logger.warning("[display] smbus2 not installed — falling back")
        except Exception:
            if backend == "i2c":
                logger.warning("[display] I²C backend unavailable — falling back")

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

    def shutdown(self) -> None:
        self._stop.set()
        self._queue.put(("stop", None, None))
        self._thread.join(timeout=3)
        if not isinstance(self._backend, MockDisplay):
            try:
                logger.info("[display] shutdown: showing exit icon via RPC")
                self._backend.show("starting")
                logger.info("[display] shutdown: icon shown, waiting 1s")
                time.sleep(1.0)
                logger.info("[display] shutdown: clearing")
                self._backend.clear()
                logger.info("[display] shutdown: clear done")
            except Exception as e:
                logger.error("[display] shutdown RPC error: %s", e)

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

    def _resolve_state(self, msg: tuple[str, str, dict]) -> str | None:
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
