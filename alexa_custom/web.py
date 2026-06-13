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

_DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"

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
        cpu_limit: int = 4,
        shutdown_callback: Callable | None = None,
        extra_event_cb: Callable | None = None,
        extra_stt_event_cb: Callable | None = None,
    ) -> None:
        self._port = port
        self._output_volume = output_volume
        self._input_gain = input_gain
        self._cpu_limit = cpu_limit
        self._shutdown_callback = shutdown_callback
        self._extra_event_cb = extra_event_cb
        self._extra_stt_event_cb = extra_stt_event_cb
        self._html = _DASHBOARD_PATH.read_text()
        self._clients: set[web.WebSocketResponse] = set()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._pending_vu: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._livekit_loop: asyncio.AbstractEventLoop | None = None
        self._livekit_stop_event: asyncio.Event | None = None
        self._handler: _WebLogHandler | None = None
        self._shutting_down = False
        self._livekit_ok = all(
            os.environ.get(k)
            for k in (
                "LIVEKIT_URL",
                "LIVEKIT_API_KEY",
                "LIVEKIT_API_SECRET",
                "LIVEKIT_ROOM",
            )
        )
        self._telegram_ok = all(
            os.environ.get(k)
            for k in (
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_CHAT_ID",
            )
        )
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
            "room_status": "closed",
            "room_answer_timeout": 0,
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
        if event == "room_status":
            self._state["room_status"] = data.get("status", "closed")
            if data.get("status") == "waiting":
                self._state["room_answer_timeout"] = data.get("timeout", 0)
            self._enqueue(
                "room_status",
                {
                    "status": self._state["room_status"],
                    "timeout": self._state["room_answer_timeout"],
                },
            )
            return
        if event == "connected":
            self._state["status"] = "Connected"
            self._state["room"] = data.get("room", "")
            self._state["room_status"] = "in_call"
            self._enqueue("room_status", {"status": "in_call", "timeout": 0})
        elif event == "starting":
            self._state["status"] = "Starting…"
        elif event == "idle":
            self._state["status"] = "Ready"
        elif event == "connecting":
            self._state["status"] = "Connecting…"
        elif event == "disconnected":
            self._state["status"] = "Disconnected — reconnecting…"
            self._state["room_status"] = "closed"
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
        elif event == "sleeping":
            self._state["stt_state"] = "sleeping"
            self._state["stt_text"] = "Sleeping"
        elif event in (
            "transcribing",
            "wake",
            "partial",
            "matched",
            "nomatch",
            "skipped",
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
        return web.Response(text=self._html, content_type="text/html")

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
                    "room_status": self._state["room_status"],
                    "room_answer_timeout": self._state["room_answer_timeout"],
                    "input_gain": self._input_gain,
                    "output_volume": self._output_volume,
                    "cpu_limit": self._cpu_limit,
                    "livekit_configured": self._livekit_ok,
                    "telegram_configured": self._telegram_ok,
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
                        await self._handle_control(payload.get("action", ""), payload)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)

        return ws

    async def _handle_control(self, action: str, payload: dict = None) -> None:
        if action == "restart":
            logger.info("Restart requested via web dashboard")
            await self._broadcast({"type": "restarting"})
            await asyncio.sleep(0.15)
            if self._shutdown_callback is not None:
                asyncio.create_task(self._shutdown_callback())
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)
        elif action == "set_volume" and payload:
            volume = payload.get("volume", 0.5)
            from alexa_custom.audio_ops import set_output_volume_direct

            set_output_volume_direct(volume)
            self._output_volume = volume
        elif action == "beep" and payload:
            frequency = payload.get("frequency", 440)
            duration = payload.get("duration", 100)
            from alexa_custom.audio_ops import play_beep

            play_beep(frequency, duration)

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

    @staticmethod
    def _ram_free_pct() -> float:
        try:
            info: dict[str, int] = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    info[k.strip()] = int(v.split()[0])
            return info["MemAvailable"] / info["MemTotal"] * 100
        except Exception:
            return 0.0

    async def _system_stats_loop(self) -> None:
        from alexa_custom.audio_hw import get_output_volume

        cpu_count = os.cpu_count() or 1
        while True:
            await asyncio.sleep(2)
            try:
                load1, load5, load15 = os.getloadavg()
            except OSError:
                load1 = load5 = load15 = 0.0
            await self._broadcast(
                {
                    "type": "system_stats",
                    "load1": load1,
                    "load5": load5,
                    "load15": load15,
                    "cpu_count": cpu_count,
                    "ram_free_pct": self._ram_free_pct(),
                    "output_volume": get_output_volume(),
                }
            )

    async def _asset_watcher_loop(
        self, watch_paths: list[Path], interval: float = 1.0
    ) -> None:
        def _collect_mtimes() -> dict[str, float]:
            mtimes: dict[str, float] = {}
            for p in watch_paths:
                candidates = (
                    [f for f in p.glob("*.yaml") if f.name != "secrets.yaml"]
                    + [f for f in p.glob("*.html")]
                    if p.is_dir()
                    else [p]
                    if p.exists()
                    else []
                )
                for f in candidates:
                    try:
                        mtimes[str(f)] = f.stat().st_mtime
                    except OSError:
                        pass
            return mtimes

        last_mtimes = await asyncio.to_thread(_collect_mtimes)
        try:
            while True:
                await asyncio.sleep(interval)
                mtimes = await asyncio.to_thread(_collect_mtimes)
                if mtimes == last_mtimes:
                    continue
                changed = [k for k in mtimes if mtimes[k] != last_mtimes.get(k)]
                last_mtimes = mtimes
                for path_str in changed:
                    if path_str.endswith(".html"):
                        try:
                            self._html = Path(path_str).read_text()
                            logger.info("Reloaded HTML: %s", path_str)
                        except OSError as e:
                            logger.warning("Failed to reload HTML %s: %s", path_str, e)
                    else:
                        logger.info("Config changed: %s", path_str)
        except asyncio.CancelledError:
            pass

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
        root.setLevel(logging.DEBUG)
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

        ww = []
        for g in config.wake_words:
            entry = {
                "word": g.word,
                "aliases": g.aliases,
                "skip_unmatched_inline": g.skip_unmatched_inline,
                "triggers": [
                    {
                        "phrase": t.phrase,
                        "aliases": t.aliases,
                        "actions": summarize(t.actions),
                    }
                    for t in g.triggers
                ],
            }
            ww.append(entry)

        gt = [
            {
                "phrase": t.phrase,
                "aliases": t.aliases,
                "actions": summarize(t.actions),
            }
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
            "global_triggers": gt,
            "llm": llm_info,
        }

    # ── LiveKit worker thread ─────────────────────────────────────────────────

    def _livekit_worker(
        self,
        run_fn: Callable,
        stop_threading: threading.Event,
        on_event_cb: Callable | None = None,
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
            loop.run_until_complete(run_fn(stop_threading, on_event_cb or self.on_event, livekit_stop))
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
        watch_paths: list[Path] | None = None,
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

            def _on_audio_config_reload(new_config):
                import pulsectl
                from alexa_custom import audio_hw

                audio_cfg = new_config.audio if new_config else None
                if audio_cfg is None:
                    return
                audio_hw.configure(new_config)
                with pulsectl.Pulse("alexa-reload"):
                    audio_hw.set_output_volume(
                        None,
                        new_config.audio.output_device,
                        new_config.audio.output_volume,
                    )
                    audio_hw.set_input_gain(
                        None, new_config.audio.input_device, new_config.audio.input_gain
                    )
                audio_hw._restore_hw_pcm()
                logger.info(
                    f"Audio config reloaded: output_volume={new_config.audio.output_volume:.2f}, "
                    f"input_gain={new_config.audio.input_gain:.2f}"
                )

            cm.register_reload_callback(_on_audio_config_reload)
            cm.start_source_watcher("alexa_custom", on_restart=_on_source_restart)
            cm.start_watcher("conf")

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
        stats_task = asyncio.create_task(self._system_stats_loop())
        watchdog_task: asyncio.Task | None = None

        all_watch = list(watch_paths or []) + [_DASHBOARD_PATH]
        asyncio.create_task(self._asset_watcher_loop(all_watch))

        if stt_params and "config" in stt_params:
            self._state["actions_config"] = self._serialize_config(stt_params["config"])

        # Chain extra event callbacks if provided
        _on_event = self.on_event
        if self._extra_event_cb:
            _cb = self._extra_event_cb
            def _chained_event(event, data, _cb_event=_on_event, _cb_extra=_cb):
                _cb_event(event, data)
                _cb_extra(event, data)
            _on_event = _chained_event

        _on_stt_event = self.on_stt_event
        if self._extra_stt_event_cb:
            _cb_stt = self._extra_stt_event_cb
            def _chained_stt(event, data, _cb=_on_stt_event, _extra=_cb_stt):
                _cb(event, data)
                _extra(event, data)
            _on_stt_event = _chained_stt

        stop_threading = threading.Event()
        livekit_thread = threading.Thread(
            target=self._livekit_worker,
            args=(run_fn, stop_threading, _on_event),
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
                on_stt_event=_on_stt_event,
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
            stats_task.cancel()
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
    watch_paths: list[Path] | None = None,
    output_volume: float = 0.5,
    input_gain: float = 1.0,
    cpu_limit: int = 4,
    shutdown_callback: Callable | None = None,
    extra_event_cb: Callable | None = None,
    extra_stt_event_cb: Callable | None = None,
) -> None:
    server = WebServer(
        port=port,
        output_volume=output_volume,
        input_gain=input_gain,
        cpu_limit=cpu_limit,
        shutdown_callback=shutdown_callback,
        extra_event_cb=extra_event_cb,
        extra_stt_event_cb=extra_stt_event_cb,
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
                watch_paths=watch_paths,
                output_volume=output_volume,
                input_gain=input_gain,
            )
        )
    except KeyboardInterrupt:
        pass
