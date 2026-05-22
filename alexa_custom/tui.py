"""Terminal UI for alexa-custom — activate with: alexa-client --tui"""
from __future__ import annotations

import asyncio
import logging
import math
import subprocess
import threading
from datetime import datetime
from collections.abc import Coroutine
from typing import Any, Callable

import numpy as np
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, RichLog, Static


# ── helpers ───────────────────────────────────────────────────────────────────

_METER_WIDTH = 26
_DECAY = 0.75  # level decay factor per ~100 ms cycle


def _db(level: float) -> float:
    return 20.0 * math.log10(max(level, 1e-9))


def _bar(level: float) -> str:
    """Return a Rich markup VU bar string with dB label."""
    db = _db(level)
    filled = max(0, min(_METER_WIDTH, round(level ** 0.5 * _METER_WIDTH)))
    if db > -6:
        color = "bold red"
    elif db > -18:
        color = "yellow"
    else:
        color = "green"
    bar = f"[{color}]{'█' * filled}[/]{'░' * (_METER_WIDTH - filled)}"
    label = f"{db:>6.1f} dB" if level > 1e-9 else "     -∞ dB"
    return f"{bar} {label}"


# ── background level monitor ──────────────────────────────────────────────────

def _audio_devices() -> tuple[str, str]:
    """Return (default_source_name, default_sink_monitor_name) via pactl."""
    try:
        out = subprocess.run(
            ['pactl', 'info'], capture_output=True, text=True, timeout=2
        ).stdout
        src, sink = '', ''
        for line in out.splitlines():
            if line.startswith('Default Source:'):
                src = line.split(':', 1)[1].strip()
            elif line.startswith('Default Sink:'):
                sink = line.split(':', 1)[1].strip() + '.monitor'
        return src or '@DEFAULT_SOURCE@', sink or '@DEFAULT_MONITOR@'
    except Exception:
        return '@DEFAULT_SOURCE@', '@DEFAULT_MONITOR@'


class LevelMonitor:
    """Reads PipeWire peak levels via parec subprocesses — no ctypes callbacks."""

    _CHUNK = 3200  # 100 ms at 16 kHz mono s16le

    def __init__(self) -> None:
        self.mic: float = 0.0
        self.spk: float = 0.0
        self._stop = threading.Event()
        self._procs: list[subprocess.Popen] = []

    def start(self) -> None:
        src, mon = _audio_devices()
        for device, attr in ((src, 'mic'), (mon, 'spk')):
            t = threading.Thread(
                target=self._monitor, args=(device, attr),
                daemon=True, name=f"level-{attr}",
            )
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for p in list(self._procs):
            try:
                p.terminate()
            except Exception:
                pass

    def _monitor(self, device: str, attr: str) -> None:
        while not self._stop.is_set():
            proc: subprocess.Popen | None = None
            try:
                proc = subprocess.Popen(
                    ['pw-record', '--target', device,
                     '--format=s16', '--channels=1', '--rate=16000', '-'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                self._procs.append(proc)
                assert proc.stdout is not None
                while not self._stop.is_set():
                    data = proc.stdout.read(self._CHUNK)
                    if not data:
                        break
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    peak = float(np.max(np.abs(samples)))
                    setattr(self, attr, max(peak, getattr(self, attr) * _DECAY))
            except Exception:
                pass
            finally:
                if proc is not None:
                    if proc in self._procs:
                        self._procs.remove(proc)
                    try:
                        proc.terminate()
                        proc.wait(timeout=1)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            if not self._stop.is_set():
                self._stop.wait(0.5)


# ── widgets ───────────────────────────────────────────────────────────────────

class VUMeter(Static):
    level: reactive[float] = reactive(0.0)

    def __init__(self, label: str, device: str = "", **kw) -> None:
        super().__init__(**kw)
        self._label = label
        self._device = device

    def render(self) -> str:
        dev = f"[dim]{self._device[:32]}[/]  " if self._device else ""
        return f"[bold]{self._label}[/]  {dev}{_bar(self.level)}"

    def watch_level(self, _: float) -> None:
        self.refresh()


class ParticipantsPanel(Static):
    participants: reactive[dict[str, int]] = reactive({}, layout=True)

    def render(self) -> str:
        if not self.participants:
            return "[dim]Waiting for participants…[/]"
        lines: list[str] = []
        for identity, tracks in self.participants.items():
            dot = "[green]●[/]" if tracks else "[dim]○[/]"
            note = (
                f"  [dim]{tracks} track{'s' if tracks != 1 else ''}[/]"
                if tracks else ""
            )
            lines.append(f"{dot} {identity}{note}")
        return "\n".join(lines)


class StatusLine(Static):
    status: reactive[str] = reactive("Starting…")
    room: reactive[str] = reactive("")

    def render(self) -> str:
        if "Connected" in self.status:
            dot = "[bold green]●[/]"
        elif "Reconnect" in self.status or "Disconnected" in self.status:
            dot = "[bold yellow]●[/]"
        else:
            dot = "[bold dim]○[/]"
        room_part = f"  [dim]│[/]  Room: [bold]{self.room}[/]" if self.room else ""
        return f" {dot}  {self.status}{room_part}"


# ── log handler ───────────────────────────────────────────────────────────────

class _TUIHandler(logging.Handler):
    _COLORS: dict[int, str] = {
        logging.DEBUG:    "dim",
        logging.INFO:     "cyan",
        logging.WARNING:  "yellow",
        logging.ERROR:    "red",
        logging.CRITICAL: "bold red",
    }

    def __init__(self, app: AlexaTUI) -> None:
        super().__init__()
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._app.call_from_thread(self._app._append_log, record)
        except Exception:
            pass


# ── main TUI app ──────────────────────────────────────────────────────────────

class AlexaTUI(App[None]):
    TITLE = "alexa-custom"
    CSS = """
    Screen { background: $surface; }

    StatusLine {
        height: 1;
        background: $panel;
        dock: top;
    }

    #main {
        height: 1fr;
    }

    #participants-wrap {
        width: 32;
        border: solid $accent;
        padding: 1 2;
    }

    #participants-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #logs {
        width: 1fr;
        border: solid $accent;
    }

    #meters {
        height: 8;
        border: solid $accent;
        padding: 1 2;
    }

    VUMeter {
        height: 1;
        margin-bottom: 1;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        run_fn: Callable[[threading.Event, Callable], Coroutine[Any, Any, None]],
        input_spec: str | None,
        output_spec: str | None,
        room: str,
        **kw,
    ) -> None:
        super().__init__(**kw)
        self._run_fn = run_fn
        self._input_spec = input_spec
        self._output_spec = output_spec
        self._room = room
        # threading.Event so the LiveKit worker thread can read it without
        # needing access to Textual's asyncio loop.
        self._stop = threading.Event()
        self._livekit_thread: threading.Thread | None = None
        self._levels = LevelMonitor()
        self._participants: dict[str, int] = {}
        self._handler: _TUIHandler | None = None
        self._removed_handlers: list[logging.Handler] = []

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusLine(id="status")
        with Horizontal(id="main"):
            with Vertical(id="participants-wrap"):
                yield Label("PARTICIPANTS (0)", id="participants-title")
                yield ParticipantsPanel(id="participants")
            yield RichLog(id="logs", highlight=True, markup=True, wrap=True)
        with Vertical(id="meters"):
            yield VUMeter(
                label="MIC ",
                device=self._input_spec or "pipewire default",
                id="mic-meter",
            )
            yield VUMeter(
                label="SPK ",
                device=self._output_spec or "pipewire default",
                id="spk-meter",
            )
        yield Footer()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        self.sub_title = f"Room: {self._room}"
        self._install_log_handler()
        self._levels.start()
        asyncio.create_task(self._poll_meters())
        # LiveKit's Rust FFI must run in its own thread with a dedicated event
        # loop — sharing Textual's loop causes a SIGSEGV in the FFI layer.
        self._livekit_thread = threading.Thread(
            target=self._livekit_worker, daemon=True, name="livekit"
        )
        self._livekit_thread.start()

    async def on_unmount(self) -> None:
        self._stop.set()
        self._levels.stop()
        # livekit worker and level-monitor threads are all daemon=True, so they
        # are killed when the process exits. Joining here blocks on room.disconnect()
        # / mic.aclose() which can take seconds — skip it for instant q-to-exit.
        root = logging.getLogger()
        if self._handler:
            root.removeHandler(self._handler)
        root.addHandler(logging.NullHandler())

    def _livekit_worker(self) -> None:
        """Runs the LiveKit session in its own asyncio event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_fn(self._stop, self._on_event))
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", StatusLine).__setattr__, "status", f"Error: {e}"
            )
        finally:
            loop.close()

    # ── log forwarding ────────────────────────────────────────────────────────

    def _install_log_handler(self) -> None:
        # Remove existing console handlers so raw log lines don't bleed into
        # the terminal while Textual is rendering.
        root = logging.getLogger()
        self._removed_handlers = [
            h for h in root.handlers[:]
            if isinstance(h, logging.StreamHandler) and not isinstance(h, _TUIHandler)
        ]
        for h in self._removed_handlers:
            root.removeHandler(h)
        self._handler = _TUIHandler(self)
        self._handler.setLevel(logging.DEBUG)
        root.addHandler(self._handler)

    def _append_log(self, record: logging.LogRecord) -> None:
        color = _TUIHandler._COLORS.get(record.levelno, "white")
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        msg = record.getMessage().replace("[", "\\[")
        self.query_one("#logs", RichLog).write(
            f"[dim]{ts}[/] [{color}]{record.levelname:<8}[/] {msg}"
        )

    # ── event bus from LiveKit session ────────────────────────────────────────

    def _on_event(self, event: str, data: dict) -> None:
        """Thread-safe: called from the asyncio task or event callbacks."""
        self.call_from_thread(self._handle_event, event, data)

    def _handle_event(self, event: str, data: dict) -> None:
        status = self.query_one("#status", StatusLine)
        if event == "connected":
            status.status = "Connected"
            status.room = data.get("room", "")
        elif event == "disconnected":
            status.status = "Disconnected — reconnecting…"
        elif event == "reconnecting":
            status.status = "Reconnecting…"
        elif event == "participant_joined":
            self._participants[data["identity"]] = 0
            self._sync_participants()
        elif event == "participant_left":
            self._participants.pop(data["identity"], None)
            self._sync_participants()
        elif event == "track_subscribed":
            identity = data["identity"]
            self._participants[identity] = self._participants.get(identity, 0) + 1
            self._sync_participants()
        elif event == "track_unsubscribed":
            identity = data["identity"]
            if identity in self._participants:
                self._participants[identity] = max(0, self._participants[identity] - 1)
                self._sync_participants()

    def _sync_participants(self) -> None:
        self.query_one("#participants", ParticipantsPanel).participants = dict(self._participants)
        self.query_one("#participants-title", Label).update(
            f"PARTICIPANTS ({len(self._participants)})"
        )

    # ── VU meter refresh ──────────────────────────────────────────────────────

    async def _poll_meters(self) -> None:
        while True:
            self.query_one("#mic-meter", VUMeter).level = self._levels.mic
            self.query_one("#spk-meter", VUMeter).level = self._levels.spk
            await asyncio.sleep(0.1)


# ── public entry point ────────────────────────────────────────────────────────

def run_tui(
    run_fn: Callable[[threading.Event, Callable], Coroutine[Any, Any, None]],
    input_spec: str | None,
    output_spec: str | None,
    room: str,
) -> None:
    AlexaTUI(
        run_fn=run_fn,
        input_spec=input_spec,
        output_spec=output_spec,
        room=room,
    ).run()
