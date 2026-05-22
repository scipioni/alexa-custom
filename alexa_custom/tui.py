"""Terminal UI for alexa-custom — activate with: alexa-client --tui"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from datetime import datetime
from collections.abc import Coroutine
from typing import Any, Callable

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
    filled = max(0, min(_METER_WIDTH, round(level**0.5 * _METER_WIDTH)))
    if db > -6:
        color = "bold red"
    elif db > -18:
        color = "yellow"
    else:
        color = "green"
    bar = f"[{color}]{'█' * filled}[/]{'░' * (_METER_WIDTH - filled)}"
    label = f"{db:>6.1f} dB" if level > 1e-9 else "     -∞ dB"
    return f"{bar} {label}"


# ── widgets ───────────────────────────────────────────────────────────────────


class STTStatus(Static):
    state: reactive[str] = reactive("idle")
    text: reactive[str] = reactive("")

    def render(self) -> str:
        if self.state == "listening":
            words = self.text or "…"
            return f"[dim]○[/]  [dim]wake words:[/] [dim italic]{words}[/]"
        elif self.state == "transcribing":
            return f"[dim]◌[/]  [dim]{self.text}[/] [dim]…[/]"
        elif self.state == "wake":
            return f'[bold yellow]◉[/]  [yellow]"{self.text}"[/] [dim]— listening for command…[/]'
        elif self.state == "partial":
            return f"[bold yellow]◉[/]  [yellow]{self.text}[/] [dim]…[/]"
        elif self.state == "matched":
            parts = self.text.split("→", 1)
            transcript = parts[0].strip()
            trigger = parts[1].strip() if len(parts) > 1 else ""
            return f'[bold green]✓[/]  [green]"{transcript}"[/] [dim]→[/] [bold]{trigger}[/]'
        elif self.state == "nomatch":
            t = f'"{self.text}" ' if self.text else ""
            return f"[bold red]✗[/]  {t}[dim red]no match[/]"
        elif self.state == "gated":
            return "[dim]⏸[/]  [dim]STT paused during call[/]"
        return "[dim]○[/]  [dim]STT inactive[/]"

    def watch_state(self, _: str) -> None:
        self.refresh()

    def watch_text(self, _: str) -> None:
        self.refresh()


class VUMeter(Static):
    level: reactive[float] = reactive(0.0)
    vol: reactive[float] = reactive(-1.0)

    def __init__(self, label: str, device: str = "", **kw) -> None:
        super().__init__(**kw)
        self._label = label
        self._device = device

    def render(self) -> str:
        dev = f"[dim]{self._device[:24]}[/]  " if self._device else ""
        vol_str = f"[cyan]{self.vol * 100:.0f}%[/]  " if self.vol >= 0 else ""
        return f"[bold]{self._label}[/]  {dev}{vol_str}{_bar(self.level)}"

    def watch_level(self, _: float) -> None:
        self.refresh()

    def watch_vol(self, _: float) -> None:
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
                if tracks
                else ""
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
        logging.DEBUG: "dim",
        logging.INFO: "cyan",
        logging.WARNING: "yellow",
        logging.ERROR: "red",
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
        height: 10;
        border: solid $accent;
        padding: 1 2;
    }

    VUMeter {
        height: 1;
        margin-bottom: 1;
    }

    STTStatus {
        height: 1;
        margin-top: 1;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        run_fn: Callable[
            [threading.Event, Callable, asyncio.Event], Coroutine[Any, Any, None]
        ],
        input_spec: str | None,
        output_spec: str | None,
        room: str,
        stt_params: dict | None = None,
        **kw,
    ) -> None:
        super().__init__(**kw)
        self._run_fn = run_fn
        self._input_spec = input_spec
        self._output_spec = output_spec
        self._room = room
        self._stt_params = stt_params  # keys: config, stop_event, telegram_client, connect_fn, connected_flag
        self._stop = threading.Event()
        self._livekit_loop: asyncio.AbstractEventLoop | None = None
        self._livekit_stop: asyncio.Event | None = None
        self._livekit_thread: threading.Thread | None = None
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
            yield STTStatus(id="stt-status")
        yield Footer()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        self.sub_title = f"Room: {self._room}"
        self._install_log_handler()
        await self._refresh_volumes()
        self.set_interval(5.0, self._refresh_volumes)
        # LiveKit's Rust FFI must run in its own thread with a dedicated event
        # loop — sharing Textual's loop causes a SIGSEGV in the FFI layer.
        self._livekit_thread = threading.Thread(
            target=self._livekit_worker, daemon=True, name="livekit"
        )
        self._livekit_thread.start()
        if self._stt_params is not None:
            from alexa_custom.stt import start_stt_thread

            start_stt_thread(
                config=self._stt_params["config"],
                stop_event=self._stt_params["stop_event"],
                telegram_client=self._stt_params["telegram_client"],
                livekit_connect_fn=self._stt_params["connect_fn"],
                livekit_connected_flag=self._stt_params["connected_flag"],
                on_stt_event=self._on_stt_event,
            )

    async def on_unmount(self) -> None:
        # Signal the livekit asyncio loop directly so it stops immediately,
        # without waiting for _bridge() polling.
        loop = self._livekit_loop
        stop = self._livekit_stop
        if loop is not None and stop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop.set)
        self._stop.set()
        if self._stt_params is not None:
            self._stt_params["stop_event"].set()
        root = logging.getLogger()
        if self._handler:
            root.removeHandler(self._handler)
        root.addHandler(logging.NullHandler())

    def _livekit_worker(self) -> None:
        """Runs the LiveKit session in its own asyncio event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._livekit_loop = loop
        self._livekit_stop = asyncio.Event()
        try:
            loop.run_until_complete(
                self._run_fn(self._stop, self._on_event, self._livekit_stop)
            )
        except Exception as e:
            self.call_from_thread(
                self.query_one("#status", StatusLine).__setattr__,
                "status",
                f"Error: {e}",
            )
        finally:
            loop.close()

    # ── volume polling ────────────────────────────────────────────────────────

    def _read_volumes(self) -> tuple[float, float]:
        import pulsectl

        mic_vol = spk_vol = -1.0
        with pulsectl.Pulse("tui-vol") as pulse:
            if self._input_spec:
                needle = self._input_spec.lower()
                src = next(
                    (
                        s
                        for s in pulse.source_list()
                        if "monitor" not in s.name
                        and (
                            needle in s.description.lower() or needle in s.name.lower()
                        )
                    ),
                    None,
                )
                if src:
                    mic_vol = src.volume.value_flat
            if self._output_spec:
                needle = self._output_spec.lower()
                snk = next(
                    (
                        s
                        for s in pulse.sink_list()
                        if needle in s.description.lower() or needle in s.name.lower()
                    ),
                    None,
                )
                if snk:
                    spk_vol = snk.volume.value_flat
        return mic_vol, spk_vol

    async def _refresh_volumes(self) -> None:
        try:
            mic_vol, spk_vol = await asyncio.to_thread(self._read_volumes)
            self.query_one("#mic-meter", VUMeter).vol = mic_vol
            self.query_one("#spk-meter", VUMeter).vol = spk_vol
        except Exception:
            pass

    # ── log forwarding ────────────────────────────────────────────────────────

    def _install_log_handler(self) -> None:
        # Remove existing console handlers so raw log lines don't bleed into
        # the terminal while Textual is rendering.
        root = logging.getLogger()
        self._removed_handlers = [
            h
            for h in root.handlers[:]
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
        try:
            self.call_from_thread(self._handle_event, event, data)
        except Exception:
            pass

    def _handle_event(self, event: str, data: dict) -> None:
        status = self.query_one("#status", StatusLine)
        if event == "connected":
            status.status = "Connected"
            status.room = data.get("room", "")
        elif event == "disconnected":
            status.status = "Disconnected — reconnecting…"
        elif event == "empty_room_timeout":
            status.status = "Disconnected — empty room"
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
        elif event == "volume_update":
            self.query_one("#mic-meter", VUMeter).level = data.get("mic", 0.0)
            self.query_one("#spk-meter", VUMeter).level = data.get("spk", 0.0)

    def _sync_participants(self) -> None:
        self.query_one("#participants", ParticipantsPanel).participants = dict(
            self._participants
        )
        self.query_one("#participants-title", Label).update(
            f"PARTICIPANTS ({len(self._participants)})"
        )

    # ── STT event bus ─────────────────────────────────────────────────────────

    def _on_stt_event(self, event: str, data: dict) -> None:
        """Thread-safe: called from the STT daemon thread."""
        try:
            self.call_from_thread(self._handle_stt_event, event, data)
        except Exception:
            pass

    def _handle_stt_event(self, event: str, data: dict) -> None:
        if event == "level":
            self.query_one("#mic-meter", VUMeter).level = data.get("mic", 0.0)
            return
        widget = self.query_one("#stt-status", STTStatus)
        if event == "listening":
            words = ", ".join(data.get("wake_words", []))
            widget.state = "listening"
            widget.text = words
        elif event == "transcribing":
            widget.state = "transcribing"
            widget.text = data.get("text", "")
        elif event == "wake":
            widget.state = "wake"
            widget.text = data.get("word", "")
        elif event == "partial":
            widget.state = "partial"
            widget.text = data.get("text", "")
        elif event == "matched":
            widget.state = "matched"
            widget.text = f"{data.get('transcript', '')} → {data.get('trigger', '')}"
        elif event == "nomatch":
            widget.state = "nomatch"
            widget.text = data.get("transcript", "")
        elif event == "gated":
            widget.state = "gated"
            widget.text = ""


# ── public entry point ────────────────────────────────────────────────────────


def run_tui(
    run_fn: Callable[
        [threading.Event, Callable, asyncio.Event], Coroutine[Any, Any, None]
    ],
    input_spec: str | None,
    output_spec: str | None,
    room: str,
    stt_params: dict | None = None,
) -> None:
    AlexaTUI(
        run_fn=run_fn,
        input_spec=input_spec,
        output_spec=output_spec,
        room=room,
        stt_params=stt_params,
    ).run()
