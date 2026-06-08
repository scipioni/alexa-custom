"""Web dashboard for alexa-custom."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from aiohttp import web, WSMsgType


logger = logging.getLogger(__name__)

# ── dashboard HTML (loaded from dashboard.html at import time) ────────────────

_HTML = (Path(__file__).parent / "dashboard.html").read_text()

# ── log handler ────────────────────────────────────────────────────────────────


class _WebLogHandler(logging.Handler):
    def __init__(self, server: WebServer) -> None:
        super().__init__()
        self._server = server

    def emit(self, record: logging.LogRecord) -> None:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        self._server._enqueue(
            "log",
            {
                "level": record.levelname,
                "ts": ts,
                "msg": record.getMessage(),
            },
        )


# ── web server ─────────────────────────────────────────────────────────────────


class WebServer:
    def __init__(
        self,
        port: int = 8080,
        output_volume: float = 0.5,
        input_gain: float = 1.0,
        shutdown_callback: Callable | None = None,
    ) -> None:
        self._port = port
        self._output_volume = output_volume
        self._input_gain = input_gain
        self._shutdown_callback = shutdown_callback
        self._clients: set[web.WebSocketResponse] = set()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._pending_vu: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._livekit_loop: asyncio.AbstractEventLoop | None = None
        self._livekit_stop_event: asyncio.Event | None = None
        self._handler: _WebLogHandler | None = None
        self._shutting_down = False
        # snapshot for hello message on new WS connects
        self._state: dict[str, Any] = {
            "status": "Starting…",
            "room": "",
            "participants": {},
            "audio_connected": False,
            "audio_conn_type": "",
            "stt_state": "idle",
            "stt_text": "",
            "actions_config": {},
            "llm_state": "idle",
        }

    # ── thread-safe enqueue ───────────────────────────────────────────────────

    def _enqueue(self, event_type: str, data: dict) -> None:
        if self._shutting_down:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        msg = {"type": event_type, **data}

        def _put():
            try:
                self._queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

        loop.call_soon_threadsafe(_put)

    def _update_pending_vu(self, mic: float, spk: float) -> None:
        """Must run on the event loop (via call_soon_threadsafe)."""
        self._pending_vu["mic"] = mic
        self._pending_vu["spk"] = spk

    # ── callbacks (same signatures as tui.py) ────────────────────────────────

    def on_event(self, event: str, data: dict) -> None:
        if event == "connected":
            self._state["status"] = "Connected"
            self._state["room"] = data.get("room", "")
        elif event == "starting":
            self._state["status"] = "Starting…"
        elif event == "idle":
            self._state["status"] = "Ready"
        elif event == "connecting":
            self._state["status"] = "Connecting…"
        elif event == "disconnected":
            self._state["status"] = "Disconnected — reconnecting…"
        elif event == "reconnecting":
            self._state["status"] = "Reconnecting…"
        elif event == "empty_room_timeout":
            self._state["status"] = "Disconnected — empty room"
        elif event == "participant_joined":
            self._state["participants"][data["identity"]] = 0
        elif event == "participant_left":
            self._state["participants"].pop(data["identity"], None)
        elif event == "track_subscribed":
            identity = data["identity"]
            self._state["participants"][identity] = (
                self._state["participants"].get(identity, 0) + 1
            )
        elif event == "track_unsubscribed":
            identity = data["identity"]
            if identity in self._state["participants"]:
                self._state["participants"][identity] = max(
                    0, self._state["participants"][identity] - 1
                )
        elif event == "volume_update":
            loop = self._loop
            if loop and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(
                        self._update_pending_vu,
                        data.get("mic", 0.0),
                        data.get("spk", 0.0),
                    )
                except Exception:
                    pass
            return
        self._enqueue(event, data)

    def on_stt_event(self, event: str, data: dict) -> None:
        if event == "level":
            loop = self._loop
            if loop and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(
                        self._update_pending_vu,
                        data.get("mic", 0.0),
                        self._pending_vu.get("spk", 0.0),
                    )
                except Exception:
                    pass
            return

        if event == "listening":
            self._state["stt_state"] = "listening"
            self._state["stt_text"] = ", ".join(data.get("wake_words", []))
        elif event in (
            "transcribing",
            "wake",
            "partial",
            "matched",
            "nomatch",
            "gated",
        ):
            self._state["stt_state"] = event
            self._state["stt_text"] = data.get(
                "text", data.get("word", data.get("transcript", ""))
            )
        elif event == "llm_thinking":
            self._state["llm_state"] = "thinking"
            self._state["stt_state"] = "llm_thinking"
            self._state["stt_text"] = data.get("transcript", "")
        elif event == "llm_reply":
            self._state["llm_state"] = "idle"
            self._state["stt_state"] = "llm_reply"
            self._state["stt_text"] = data.get("reply", "")
        elif event == "llm_unreachable":
            self._state["llm_state"] = "idle"
            self._state["stt_state"] = "llm_unreachable"
            self._state["stt_text"] = ""

        self._enqueue("stt", {"state": event, **data})

    def on_audio_status(self, connected: bool, conn_type: str) -> None:
        self._state["audio_connected"] = connected
        self._state["audio_conn_type"] = conn_type
        self._enqueue("audio_status", {"connected": connected, "conn_type": conn_type})

    # ── HTTP / WebSocket routes ───────────────────────────────────────────────

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_HTML, content_type="text/html")

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)

        participants_list = [
            {"identity": k, "tracks": v} for k, v in self._state["participants"].items()
        ]
        await ws.send_str(
            json.dumps(
                {
                    "type": "hello",
                    "status": self._state["status"],
                    "room": self._state["room"],
                    "participants": participants_list,
                    "audio_connected": self._state["audio_connected"],
                    "audio_conn_type": self._state["audio_conn_type"],
                    "stt_state": self._state["stt_state"],
                    "stt_text": self._state["stt_text"],
                    "actions_config": self._state["actions_config"],
                    "llm_state": self._state["llm_state"],
                }
            )
        )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "control":
                        await self._handle_control(payload.get("action", ""))
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)

        return ws

    async def _handle_control(self, action: str) -> None:
        if action == "restart":
            logger.info("Restart requested via web dashboard")
            await self._broadcast({"type": "restarting"})
            await asyncio.sleep(0.15)
            if self._shutdown_callback is not None:
                asyncio.create_task(self._shutdown_callback())
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)

    # ── broadcast helpers ─────────────────────────────────────────────────────

    async def _broadcast(self, msg: dict) -> None:
        if not self._clients:
            return
        text = json.dumps(msg)
        dead: set[web.WebSocketResponse] = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(text)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _broadcast_loop(self) -> None:
        while True:
            msg = await self._queue.get()
            await self._broadcast(msg)

    async def _vu_flush_loop(self) -> None:
        from alexa_custom.audio import get_playback_level

        while True:
            await asyncio.sleep(0.25)
            spk = max(self._pending_vu.get("spk", 0.0), get_playback_level())
            mic = self._pending_vu.get("mic", 0.0)
            if (self._pending_vu or spk > 0) and self._clients:
                await self._broadcast({"type": "volume_update", "mic": mic, "spk": spk})
                self._pending_vu.clear()

    async def _prune_clients_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            self._clients = {ws for ws in self._clients if not ws.closed}

    async def _stt_watchdog_loop(
        self, stt_thread_holder: list, stt_params: dict
    ) -> None:
        from alexa_custom.stt import start_stt_thread

        while True:
            await asyncio.sleep(5)
            if not stt_thread_holder[0].is_alive():
                logger.warning("STT thread died unexpectedly — restarting")
                await self._broadcast({"type": "stt", "state": "stt_dead"})
                new_stop = threading.Event()
                stt_params["stop_event"] = new_stop
                new_thread = start_stt_thread(
                    config=stt_params["config"],
                    stop_event=new_stop,
                    telegram_client=stt_params["telegram_client"],
                    livekit_connect_fn=stt_params["connect_fn"],
                    livekit_connected_flag=stt_params["connected_flag"],
                    on_stt_event=self.on_stt_event,
                    stt_ready_event=stt_params.get("stt_ready_event"),
                )
                stt_thread_holder[0] = new_thread

    # ── logging ───────────────────────────────────────────────────────────────

    def _install_log_handler(self) -> None:
        root = logging.getLogger()
        self._handler = _WebLogHandler(self)
        self._handler.setLevel(logging.DEBUG)
        root.addHandler(self._handler)

    def _uninstall_log_handler(self) -> None:
        if self._handler:
            logging.getLogger().removeHandler(self._handler)

    def _serialize_config(self, config: Any) -> dict:
        from alexa_custom.config import ActionsConfig

        if not isinstance(config, ActionsConfig):
            return {}

        def summarize(actions):
            res = []
            for a in actions:
                entry = {"type": a.type}
                txt = a.params.get(
                    "text", a.params.get("message", a.params.get("command", ""))
                )
                if len(txt) > 30:
                    txt = txt[:27] + "..."

                if a.type == "say":
                    entry["label"] = f"say: {txt}"
                elif a.type == "ask":
                    entry["label"] = f"ask: {txt}"
                    entry["on_reply"] = [
                        {"phrase": r.phrase, "actions": summarize(r.actions)}
                        for r in a.on_reply
                    ]
                    if a.on_else:
                        entry["on_else"] = summarize(a.on_else)
                elif a.type == "mqtt_publish":
                    entry["label"] = f"mqtt: {a.params.get('topic', '')}"
                elif a.type == "telegram":
                    entry["label"] = "telegram"
                elif a.type == "shell":
                    entry["label"] = f"shell: {txt}"
                elif a.type == "log":
                    entry["label"] = f"log: {txt}"
                else:
                    entry["label"] = a.type
                res.append(entry)
            return res

        from alexa_custom.stt import _build_confuser_set

        confuser_set = _build_confuser_set(config.wake_words, config.stt.stage1)

        ww = []
        for g in config.wake_words:
            entry = {
                "word": g.word,
                "aliases": g.aliases,
                "triggers": [
                    {"phrase": t.phrase, "actions": summarize(t.actions)}
                    for t in g.triggers
                ],
            }
            ww.append(entry)

        gt = [
            {"phrase": t.phrase, "actions": summarize(t.actions)}
            for t in config.triggers
        ]

        llm_info: dict | None = None
        if config.llm is not None:
            host = config.llm.host
            # strip protocol and port for display
            display_host = (
                host.replace("https://", "").replace("http://", "").split(":")[0]
            )
            llm_info = {
                "enabled": True,
                "model": config.llm.model,
                "host": display_host,
                "fallback": config.llm.fallback_on_no_match,
            }

        return {
            "wake_words": ww,
            "confusers": sorted(confuser_set),
            "global_triggers": gt,
            "llm": llm_info,
        }

    # ── LiveKit worker thread ─────────────────────────────────────────────────

    def _livekit_worker(
        self,
        run_fn: Callable,
        stop_threading: threading.Event,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._livekit_loop = loop
        livekit_stop = asyncio.Event()
        self._livekit_stop_event = livekit_stop

        def _exc_handler(lp: asyncio.AbstractEventLoop, context: dict) -> None:
            if isinstance(context.get("exception"), asyncio.QueueFull):
                return
            lp.default_exception_handler(context)

        loop.set_exception_handler(_exc_handler)
        try:
            loop.run_until_complete(run_fn(stop_threading, self.on_event, livekit_stop))
        except Exception as e:
            self._enqueue("error", {"msg": str(e)})
        finally:
            loop.close()

    # ── main coroutine ────────────────────────────────────────────────────────

    async def run(
        self,
        run_fn: Callable,
        input_spec: str | None,
        output_spec: str | None,
        room: str,
        stt_params: dict | None = None,
        hot_reload: bool = False,
        output_volume: float = 0.5,
        input_gain: float = 1.0,
    ) -> None:
        self._loop = asyncio.get_running_loop()
        self._install_log_handler()

        if hot_reload:
            from alexa_custom.config_manager import ConfigManager

            async def _on_source_restart():
                await self._broadcast({"type": "restarting"})

            cm = ConfigManager(None)
            cm.start_source_watcher("alexa_custom", on_restart=_on_source_restart)

        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self._port)
        await site.start()
        logger.info("Web dashboard available at http://0.0.0.0:%d", self._port)

        broadcast_task = asyncio.create_task(self._broadcast_loop())
        vu_task = asyncio.create_task(self._vu_flush_loop())
        prune_task = asyncio.create_task(self._prune_clients_loop())
        watchdog_task: asyncio.Task | None = None

        if stt_params and "config" in stt_params:
            self._state["actions_config"] = self._serialize_config(stt_params["config"])

        stop_threading = threading.Event()
        livekit_thread = threading.Thread(
            target=self._livekit_worker,
            args=(run_fn, stop_threading),
            daemon=True,
            name="livekit-web",
        )
        livekit_thread.start()

        from alexa_custom.audio import AudioWatcher

        audio_watcher = AudioWatcher(
            input_spec=input_spec,
            output_spec=output_spec,
            on_status_change=self.on_audio_status,
            output_volume=output_volume,
            input_gain=input_gain,
        )
        audio_watcher.start()

        if stt_params is not None:
            from alexa_custom.stt import start_stt_thread

            stt_thread = start_stt_thread(
                config=stt_params["config"],
                stop_event=stt_params["stop_event"],
                telegram_client=stt_params["telegram_client"],
                livekit_connect_fn=stt_params["connect_fn"],
                livekit_connected_flag=stt_params["connected_flag"],
                on_stt_event=self.on_stt_event,
                stt_ready_event=stt_params.get("stt_ready_event"),
            )
            stt_thread_holder = [stt_thread]
            watchdog_task = asyncio.create_task(
                self._stt_watchdog_loop(stt_thread_holder, stt_params)
            )

        try:
            await asyncio.Future()  # blocks until cancelled (Ctrl+C)
        except asyncio.CancelledError:
            pass
        finally:
            self._shutting_down = True
            self._uninstall_log_handler()

            lk_loop = self._livekit_loop
            lk_stop = self._livekit_stop_event
            if lk_loop and lk_stop and not lk_loop.is_closed():
                lk_loop.call_soon_threadsafe(lk_stop.set)
            stop_threading.set()
            if stt_params:
                stt_params["stop_event"].set()
            audio_watcher.stop()
            for ws in list(self._clients):
                try:
                    await ws.close()
                except Exception:
                    pass
            broadcast_task.cancel()
            vu_task.cancel()
            prune_task.cancel()
            if watchdog_task is not None:
                watchdog_task.cancel()
            await runner.cleanup()


# ── public entry point ─────────────────────────────────────────────────────────


def run_web(
    run_fn: Callable,
    input_spec: str | None,
    output_spec: str | None,
    room: str,
    stt_params: dict | None = None,
    port: int = 8080,
    hot_reload: bool = False,
    output_volume: float = 0.5,
    input_gain: float = 1.0,
    shutdown_callback: Callable | None = None,
) -> None:
    server = WebServer(
        port=port,
        output_volume=output_volume,
        input_gain=input_gain,
        shutdown_callback=shutdown_callback,
    )
    try:
        asyncio.run(
            server.run(
                run_fn,
                input_spec,
                output_spec,
                room,
                stt_params,
                hot_reload=hot_reload,
                output_volume=output_volume,
                input_gain=input_gain,
            )
        )
    except KeyboardInterrupt:
        pass
