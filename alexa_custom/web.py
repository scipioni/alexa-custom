"""Web dashboard for alexa-custom."""

from __future__ import annotations

import asyncio
import copy
import fcntl
import json
import logging
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from aiohttp import web, WSMsgType

from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

_BOOLISH = frozenset({"true", "false", "yes", "no", "on", "off"})


def _quote_boolish_str(dumper, data: str):
    if data.lower() in _BOOLISH:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return dumper.represent_str(data)


yaml.representer.add_representer(str, _quote_boolish_str)


@contextmanager
def _file_lock(filepath: Path, exclusive: bool = True) -> None:
    """Acquire file lock for concurrent access protection.

    Args:
        filepath: Path to file to lock
        exclusive: True for write lock, False for shared read lock

    Yields:
        None

    Raises:
        IOError: If lock cannot be acquired
    """
    with open(filepath, "a+") as f:
        try:
            if exclusive:
                fcntl.flock(f, fcntl.LOCK_EX)
            else:
                fcntl.flock(f, fcntl.LOCK_SH)
            yield
            fcntl.flock(f, fcntl.LOCK_UN)
        except (IOError, BlockingIOError) as e:
            fcntl.flock(f, fcntl.LOCK_UN)
            raise IOError(f"Failed to acquire file lock for {filepath}: {e}")


logger = logging.getLogger(__name__)

_DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"

# ── log handler ────────────────────────────────────────────────────────────────


class _WebLogHandler(logging.Handler):
    def __init__(self, server: WebServer) -> None:
        super().__init__()
        self._server = server

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO:
            if not (record.name and record.name.startswith("alexa_custom")):
                return
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
        cpu_limit: float = 1.0,
        shutdown_callback: Callable | None = None,
        extra_event_cb: Callable | None = None,
        extra_stt_event_cb: Callable | None = None,
        hot_reload: bool = False,
        conf_dir: Path = Path("conf"),
    ) -> None:
        self._port = port
        self._conf_dir = Path(conf_dir)
        self._output_volume = output_volume
        self._input_gain = input_gain
        self._cpu_limit = cpu_limit
        self._shutdown_callback = shutdown_callback
        self._extra_event_cb = extra_event_cb
        self._extra_stt_event_cb = extra_stt_event_cb
        self._config_manager: Any = None
        self._html = _DASHBOARD_PATH.read_text()
        self._clients: set[web.WebSocketResponse] = set()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._pending_vu: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._livekit_loop: asyncio.AbstractEventLoop | None = None
        self._livekit_stop_event: asyncio.Event | None = None
        self._handler: _WebLogHandler | None = None
        self._shutting_down = False
        self._active_session: dict | None = None

        if hot_reload:
            from alexa_custom.config_manager import ConfigManager

            cm = ConfigManager(None)
            self._config_manager = cm

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
        self._history_file = Path("conf/history.jsonl")
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

    # ── persistent history helpers ────────────────────────────────────────────

    async def _append_history_log(self, session_data: dict) -> None:
        """Appends a single JSON line to the configured history file asynchronously."""

        def _write():
            try:
                self._history_file.parent.mkdir(parents=True, exist_ok=True)
                with _file_lock(self._history_file, exclusive=True):
                    with self._history_file.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(session_data, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(
                    "Failed to append history to file %s: %s", self._history_file, e
                )

        loop = self._loop or asyncio.get_running_loop()
        await loop.run_in_executor(None, _write)

    async def _clear_history_log(self) -> None:
        """Safely clears/truncates the persistent history file on disk."""

        def _clear():
            try:
                if self._history_file.exists():
                    with _file_lock(self._history_file, exclusive=True):
                        with self._history_file.open("w", encoding="utf-8"):
                            pass
            except Exception as e:
                logger.error(
                    "Failed to truncate history file %s: %s", self._history_file, e
                )

        loop = self._loop or asyncio.get_running_loop()
        await loop.run_in_executor(None, _clear)

    async def _flag_history_log_fp(self, session_id: str) -> None:
        """Locates a session by ID in history.jsonl, marks it as false positive, and updates the file atomically."""

        def _update():
            if not self._history_file.exists():
                return
            try:
                lines = []
                updated = False
                with _file_lock(self._history_file, exclusive=True):
                    with self._history_file.open("r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                if data.get("session_id") == session_id:
                                    data.setdefault("feedback", {})[
                                        "false_positive"
                                    ] = True
                                    data["feedback"]["user_flagged"] = True
                                    line = json.dumps(data, ensure_ascii=False) + "\n"
                                    updated = True
                            except Exception:
                                pass
                            lines.append(line)
                    if updated:
                        with self._history_file.open("w", encoding="utf-8") as f:
                            f.writelines(lines)
            except Exception as e:
                logger.error(
                    "Failed to flag history session %s as false positive: %s",
                    session_id,
                    e,
                )

        loop = self._loop or asyncio.get_running_loop()
        await loop.run_in_executor(None, _update)

    async def _read_last_history_entries(self, limit: int = 20) -> list[dict]:
        """Reads the last limit entries from history.jsonl in chronological order."""

        def _read() -> list[dict]:
            if not self._history_file.exists():
                return []
            try:
                with _file_lock(self._history_file, exclusive=False):
                    with self._history_file.open("r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
                entries = []
                for line_str in lines[-limit:]:
                    try:
                        entries.append(json.loads(line_str))
                    except Exception:
                        pass
                return entries
            except Exception as e:
                logger.error(
                    "Failed to read last history entries from %s: %s",
                    self._history_file,
                    e,
                )
                return []

        loop = self._loop or asyncio.get_running_loop()
        return await loop.run_in_executor(None, _read)

    def _process_history_event(self, event: str, data: dict) -> None:
        """Processes STT lifecycle events on the main event loop to aggregate and persist sessions."""
        import uuid

        def _flush_session():
            if self._active_session:
                session = self._active_session
                self._active_session = None

                # Drop superseded partial-only sessions. When a wake word is
                # re-finalized together with the command inside the open window
                # (one-breath, e.g. "ehi serena volume basso"), the recognition
                # loop emits a fresh `wake` event that flushes the prior session.
                # That prior session may only ever have captured a `transcribing`
                # partial — never a finalizing matched/nomatch — so persisting it
                # produces a phantom history entry that looks like a nomatch even
                # though the command matched in the next session. Discard it.
                if session.pop("_partial_only", False):
                    return

                if not session.get("transcript"):
                    session["transcript"] = {
                        "text": "",
                        "is_matched": False,
                        "match_phrase": "",
                        "match_score": 0,
                    }
                    session.setdefault("diagnostics", {})["gated"] = True

                asyncio.create_task(self._append_history_log(session))
                asyncio.create_task(
                    self._broadcast({"type": "history_item", "session": session})
                )

        if event == "matched" and not self._active_session:
            session_id = (
                f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            )
            self._active_session = {
                "session_id": session_id,
                "timestamp": datetime.now().isoformat() + "Z",
                "wake": {
                    "word": "",
                    "timeout": 0.0,
                    "confidence": None,
                },
                "diagnostics": {
                    "max_mic_level": self._pending_vu.get("mic", 0.0),
                    "rms_threshold": self._pending_vu.get("rms_threshold", 0.0),
                    "gated": False,
                    "input_gain": self._input_gain,
                    "cpu_limit": self._cpu_limit,
                },
                "transcript": None,
                "action": None,
                "llm": None,
                "feedback": {
                    "false_positive": False,
                    "user_flagged": False,
                },
            }

        if event == "wake":
            _flush_session()
            session_id = (
                f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            )
            self._active_session = {
                "session_id": session_id,
                "timestamp": datetime.now().isoformat() + "Z",
                "wake": {
                    "word": data.get("word", "unknown"),
                    "timeout": data.get("timeout", 0.0),
                    "confidence": self._pending_vu.get("confidence"),
                },
                "diagnostics": {
                    "max_mic_level": self._pending_vu.get("mic", 0.0),
                    "rms_threshold": self._pending_vu.get("rms_threshold", 0.0),
                    "gated": False,
                    "input_gain": self._input_gain,
                    "cpu_limit": self._cpu_limit,
                },
                "transcript": None,
                "action": None,
                "llm": None,
                "feedback": {
                    "false_positive": False,
                    "user_flagged": False,
                },
            }

        elif self._active_session:
            mic_val = self._pending_vu.get("mic", 0.0)
            if mic_val > self._active_session["diagnostics"]["max_mic_level"]:
                self._active_session["diagnostics"]["max_mic_level"] = mic_val

            if event == "gated":
                self._active_session["diagnostics"]["gated"] = True
                self._active_session["_partial_only"] = False
                _flush_session()

            elif event == "transcribing":
                text = data.get("text", "")
                if text:
                    if not self._active_session["transcript"]:
                        self._active_session["transcript"] = {
                            "text": text,
                            "is_matched": False,
                            "match_phrase": "",
                            "match_score": 0,
                        }
                    else:
                        self._active_session["transcript"]["text"] = text
                    # Mark as not-yet-finalized: a finalizing matched/nomatch/gated
                    # event clears this. A session flushed while still flagged was
                    # superseded mid-recognition and is dropped (see _flush_session).
                    self._active_session["_partial_only"] = True

            elif event in ("matched", "nomatch"):
                transcript_text = data.get("transcript", data.get("text", ""))
                is_matched = event == "matched"

                action_info = None
                actions = data.get("actions", [])
                if is_matched and actions:
                    first = actions[0]
                    action_info = {
                        "type": first.get("type", "unknown"),
                        "params": first.get("params", {}),
                    }

                self._active_session["transcript"] = {
                    "text": transcript_text,
                    "is_matched": is_matched,
                    "match_phrase": data.get("phrase", ""),
                    "match_score": data.get("score", 0),
                }
                self._active_session["_partial_only"] = False
                if action_info:
                    self._active_session["action"] = action_info

                if is_matched:
                    _flush_session()

            elif event == "llm_thinking":
                self._active_session["llm"] = {
                    "thinking": True,
                    "prompt": data.get("transcript", ""),
                    "reply": "",
                    "duration_ms": 0,
                }
                self._llm_thinking_start = datetime.now()

            elif event in ("llm_reply", "llm_unreachable"):
                if self._active_session and self._active_session.get("llm"):
                    duration = 0
                    if hasattr(self, "_llm_thinking_start"):
                        duration = int(
                            (datetime.now() - self._llm_thinking_start).total_seconds()
                            * 1000
                        )
                    self._active_session["llm"]["thinking"] = False
                    self._active_session["llm"]["reply"] = data.get("reply", "")
                    self._active_session["llm"]["duration_ms"] = duration
                _flush_session()

        if event in ("listening", "sleeping"):
            _flush_session()

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

    def _update_pending_vu(
        self,
        mic: float,
        spk: float,
        rms_threshold: float | None = None,
        confidence: float | None = None,
        adaptive: bool | None = None,
    ) -> None:
        """Must run on the event loop (via call_soon_threadsafe)."""
        self._pending_vu["mic"] = mic
        self._pending_vu["spk"] = spk
        if rms_threshold is not None:
            self._pending_vu["rms_threshold"] = rms_threshold
        if confidence is not None:
            self._pending_vu["confidence"] = confidence
        if adaptive is not None:
            self._pending_vu["adaptive"] = adaptive

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
        if event == "action_error":
            # An action could not complete (e.g. mqtt_publish with no broker).
            # Surface it to the dashboard as a transient error toast. Not a
            # session-lifecycle event, so skip history aggregation.
            self._enqueue(
                "toast",
                {"message": data.get("message", "Action failed"), "level": "error"},
            )
            return
        if event == "level":
            loop = self._loop
            if loop and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(
                        self._update_pending_vu,
                        data.get("mic", 0.0),
                        self._pending_vu.get("spk", 0.0),
                        data.get("rms_threshold"),
                        data.get("confidence"),
                        data.get("adaptive"),
                    )
                except Exception:
                    pass
            return

        # Process history session aggregation on the main event loop thread-safely
        loop_hist = self._loop
        if loop_hist and not loop_hist.is_closed():
            try:
                loop_hist.call_soon_threadsafe(self._process_history_event, event, data)
            except Exception:
                pass

        if event == "listening":
            self._state["stt_state"] = "listening"
            self._state["stt_text"] = ", ".join(data.get("wake_words", []))
        elif event == "sleeping":
            self._state["stt_state"] = "sleeping"
            wake_up = data.get("wake_up_phrase")
            if wake_up:
                self._state["stt_text"] = f"sleeping... wait for wake up {wake_up}"
            else:
                self._state["stt_text"] = "Sleeping"
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
                    "history": await self._read_last_history_entries(20),
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
                        try:
                            await self._handle_control(payload.get("action", ""))
                        except Exception:
                            logger.exception("Error handling control action")
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
                self._shutdown_callback()
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)
        elif action == "clear_history":
            logger.info("Clear history requested via web dashboard")
            self._active_session = None
            await self._clear_history_log()
            await self._broadcast({"type": "history_cleared"})
        elif action.startswith("flag_fp:"):
            session_id = action.split(":", 1)[1]
            logger.info("Flag false positive requested for session: %s", session_id)
            await self._flag_history_log_fp(session_id)
            await self._broadcast({"type": "history_flagged", "session_id": session_id})

    # ── config API endpoints ───────────────────────────────────────────────────────

    async def _handle_config_get(self, request: web.Request) -> web.Response:
        """Return current configuration as JSON"""
        try:
            from alexa_custom.config import load_config

            config_obj = load_config(self._conf_dir / "config.yaml")
            config_dict = self._serialize_config(config_obj)
            return web.json_response(config_dict)
        except Exception as e:
            logger.error("Failed to load config: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_config_update(self, request: web.Request) -> web.Response:
        """Update configuration via POST with partial updates"""
        config_path = self._conf_dir / "config.yaml"
        temp_path = self._conf_dir / "config.yaml.tmp"
        try:
            data = await request.json()

            is_valid, error_msg = self._validate_config(data)
            if not is_valid:
                return web.json_response({"error": error_msg}, status=400)

            from alexa_custom.config import load_config

            current_config = load_config(config_path)
            current_dict = self._serialize_config(current_config)
            merged_config = self._merge_configs(current_dict, data)
            merged_config = self._strip_action_derived(merged_config)

            raw = yaml.load(config_path)
            if raw is None:
                raw = {}
            self._deep_update_raw(raw, merged_config)

            try:
                with _file_lock(config_path, exclusive=True):
                    yaml.dump(raw, temp_path)
                    temp_path.replace(config_path)
            except IOError as e:
                logger.error("Failed to acquire config file lock: %s", e)
                return web.json_response(
                    {"error": "Configuration file is locked by another process"},
                    status=423,
                )

            if self._config_manager:
                self._config_manager._reload(config_path)

            # Return updated config so UI syncs without a separate fetch
            updated_config = load_config(config_path)
            updated_dict = self._serialize_config(updated_config)
            return web.json_response({"status": "ok", "config": updated_dict})

        except Exception as e:
            logger.error("Failed to update config: %s", e)
            if temp_path.exists():
                temp_path.unlink()
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_config_replace(self, request: web.Request) -> web.Response:
        """Replace entire configuration via PUT"""
        from alexa_custom.config import load_config

        config_path = self._conf_dir / "config.yaml"
        temp_path = self._conf_dir / "config.yaml.tmp"
        try:
            data = await request.json()

            is_valid, error_msg = self._validate_config(data)
            if not is_valid:
                return web.json_response({"error": error_msg}, status=400)

            raw = yaml.load(config_path)
            if raw is None:
                raw = {}
            self._deep_update_raw(raw, self._strip_action_derived(data))

            try:
                with _file_lock(config_path, exclusive=True):
                    yaml.dump(raw, temp_path)
                    temp_path.replace(config_path)
            except IOError as e:
                logger.error("Failed to acquire config file lock: %s", e)
                return web.json_response(
                    {"error": "Configuration file is locked by another process"},
                    status=423,
                )

            if self._config_manager:
                self._config_manager._reload(config_path)

            # Return updated config so UI syncs without a separate fetch
            updated_config = load_config(config_path)
            updated_dict = self._serialize_config(updated_config)
            return web.json_response({"status": "ok", "config": updated_dict})

        except Exception as e:
            logger.error("Failed to replace config: %s", e)
            if temp_path.exists():
                temp_path.unlink()
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_config_defaults(self, request: web.Request) -> web.Response:
        """Return factory default configuration from conf.example/config.yaml"""
        try:
            from alexa_custom.config import load_config

            defaults = load_config("conf.example/config.yaml")
            result = self._serialize_config(defaults)
            return web.json_response(result)
        except Exception as e:
            logger.error("Failed to load factory defaults: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Liveness/at-a-glance status for monitoring (no auth, no secrets)."""
        from alexa_custom import metrics

        return web.json_response(
            {
                "status": "ok",
                "uptime_s": round(metrics.uptime_s(), 1),
                "audio_connected": self._state.get("audio_connected", False),
                "audio_conn_type": self._state.get("audio_conn_type", ""),
                "stt_state": self._state.get("stt_state", "idle"),
                "room_status": self._state.get("room_status", "closed"),
            }
        )

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """Full metrics snapshot (counters, gauges, timing summaries)."""
        from alexa_custom import metrics

        return web.json_response(metrics.snapshot())

    def _validate_config(self, config: dict | Any) -> tuple[bool, str | None]:
        """Validate configuration values"""
        if not isinstance(config, dict):
            return False, "Config must be a dictionary"

        if "wake_words" in config:
            for ww in config["wake_words"]:
                word = ww if isinstance(ww, str) else ww.get("word", "")
                if not word:
                    return False, "Wake word cannot be empty"

        if "recognition" in config:
            rec = config["recognition"]
            if "wake_window" in rec:
                wake_window = rec["wake_window"]
                if wake_window is not None and wake_window <= 0:
                    return False, "wake_window must be positive"
            if "matching_threshold" in rec:
                threshold = rec["matching_threshold"]
                if threshold is not None and not (0 <= threshold <= 100):
                    return False, "matching_threshold must be between 0 and 100"
            if "reply_matching_threshold" in rec:
                threshold = rec["reply_matching_threshold"]
                if threshold is not None and not (0 <= threshold <= 100):
                    return False, "reply_matching_threshold must be between 0 and 100"
            _valid_algos = {
                "token_set_ratio",
                "token_sort_ratio",
                "levenshtein",
                "ratio",
            }
            if (
                "matching_algorithm" in rec
                and rec["matching_algorithm"] not in _valid_algos
            ):
                return False, f"Invalid matching_algorithm: {rec['matching_algorithm']}"
            if (
                "reply_matching_algorithm" in rec
                and rec["reply_matching_algorithm"] not in _valid_algos
            ):
                return (
                    False,
                    f"Invalid reply_matching_algorithm: {rec['reply_matching_algorithm']}",
                )

        if "stt" in config:
            stt = config["stt"]
            if "backend" in stt:
                valid_backends = ["vosk", "sherpa-onnx"]
                if stt["backend"] not in valid_backends:
                    return False, f"Invalid STT backend: {stt['backend']}"
            if "rms_threshold" in stt:
                rms = stt["rms_threshold"]
                if rms is not None and not (0 <= rms <= 1):
                    return False, "rms_threshold must be between 0 and 1"

        if "audio" in config:
            audio = config["audio"]
            if "output_volume" in audio:
                vol = audio["output_volume"]
                if vol is not None and not (0 <= vol <= 1):
                    return False, "output_volume must be between 0 and 1"
            if "input_gain" in audio:
                gain = audio["input_gain"]
                if gain is not None and gain < 0:
                    return False, "input_gain cannot be negative"

        if "tts" in config:
            tts = config["tts"]
            if "backend" in tts:
                valid_backends = ["piper", "pico"]
                if tts["backend"] not in valid_backends:
                    return False, f"Invalid TTS backend: {tts['backend']}"

        return True, None

    def _merge_configs(self, current: dict, updates: dict) -> dict:
        """Merge updates into current config (deep merge for nested dicts)"""
        result = copy.deepcopy(current)

        for key, value in updates.items():
            if key == "wake_words" and isinstance(value, list) and key in result:
                result[key] = self._merge_wake_words(result[key], value)
            elif (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value

        return result

    def _merge_wake_words(self, current: list, updates: list) -> list:
        """Replace wake words list (flat string list in new schema).

        Accepts both string lists and legacy {word: ...} dicts.
        """
        result = []
        for u in updates:
            if isinstance(u, str):
                result.append(u)
            elif isinstance(u, dict) and u.get("word"):
                result.append(u["word"])
            else:
                result.append(u)

        return result

    @staticmethod
    def _strip_action_derived(payload: dict) -> dict:
        """Drop keys that originate from conf/actions/*.yaml, not the editor.

        load_config() merges wake_triggers from action files into each wake
        group's `.triggers`, and global triggers into the top-level list. The
        serializer re-emits both; if we persisted them into config.yaml they
        would be merged again on the next load, duplicating and diverging from
        the action files (their source of truth). The editor only owns
        word/aliases/id/skip_unmatched_inline on wake words.
        """
        payload = copy.deepcopy(payload)
        payload.pop("triggers", None)
        return payload

    def _deep_update_raw(self, raw: Any, updates: dict) -> None:
        """Recursively merge `updates` into the ruamel `raw` mapping in place.

        Only leaf keys present in `updates` are overwritten; nested mappings on
        disk (e.g. stt.model_path, num_threads, …) that the editor does not
        serialize are preserved. A shallow dict.update() would replace whole
        nested mappings and silently wipe those keys.
        """
        for key, value in updates.items():
            if key in raw and isinstance(raw[key], dict) and isinstance(value, dict):
                self._deep_update_raw(raw[key], value)
            else:
                raw[key] = value

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
            rms_threshold = self._pending_vu.get("rms_threshold")
            confidence = self._pending_vu.get("confidence")
            adaptive = self._pending_vu.get("adaptive")

            if (self._pending_vu or spk > 0) and self._clients:
                msg = {"type": "volume_update", "mic": mic, "spk": spk}
                if rms_threshold is not None:
                    msg["rms_threshold"] = rms_threshold
                if confidence is not None:
                    msg["confidence"] = confidence
                if adaptive is not None:
                    msg["adaptive"] = adaptive
                await self._broadcast(msg)
                self._pending_vu.clear()

    async def _prune_clients_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            self._clients = {ws for ws in self._clients if not ws.closed}

    async def _system_stats_loop(self) -> None:
        cpu_count = os.cpu_count() or 1
        from alexa_custom.audio_hw import get_input_gain, get_output_volume

        while True:
            await asyncio.sleep(2)
            try:
                load1, load5, load15 = os.getloadavg()
            except OSError:
                load1 = load5 = load15 = 0.0

            ram_free_pct: float | None = None
            try:
                meminfo: dict[str, int] = {}
                with open("/proc/meminfo") as _f:
                    for _line in _f:
                        _k, _v = _line.split(":", 1)
                        meminfo[_k.strip()] = int(_v.split()[0])
                total = meminfo.get("MemTotal", 0)
                available = meminfo.get("MemAvailable", 0)
                if total > 0:
                    ram_free_pct = available / total * 100
            except Exception:
                pass

            try:
                vol = get_output_volume()
            except Exception:
                vol = None

            try:
                gain = get_input_gain()
            except Exception:
                gain = None

            msg = {
                "type": "system_stats",
                "load1": load1,
                "load5": load5,
                "load15": load15,
                "cpu_count": cpu_count,
            }
            if ram_free_pct is not None:
                msg["ram_free_pct"] = round(ram_free_pct, 1)
            if vol is not None:
                msg["output_volume"] = vol
            if gain is not None:
                msg["input_gain"] = gain

            await self._broadcast(msg)

    async def _asset_watcher_loop(
        self, watch_paths: list[Path], interval: float = 1.0
    ) -> None:
        def _collect_mtimes() -> dict[str, float]:
            mtimes: dict[str, float] = {}
            for p in watch_paths:
                candidates = (
                    [
                        f
                        for f in p.glob("*.yaml")
                        if f.name not in ("secrets.yaml", "state.yaml")
                    ]
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
                await self._broadcast({"type": "reload"})
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
                    config=lambda: (
                        self._config_manager.config
                        if self._config_manager
                        and self._config_manager.config is not None
                        else stt_params["config"]
                    ),
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
        self._handler = _WebLogHandler(self)
        self._handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(self._handler)

    def _uninstall_log_handler(self) -> None:
        if self._handler:
            logging.getLogger().removeHandler(self._handler)

    @staticmethod
    def _serialize_trigger(t) -> dict:
        return {
            "phrase": t.phrase,
            "commands": t.commands,
            "aliases": t.aliases,
            "actions": WebServer._serialize_action_list(t.actions),
            "with_wake": t.with_wake,
            "sleeping_only": any(a.type == "start_listening" for a in t.actions),
            "tag": t.tag,
        }

    @staticmethod
    def _serialize_action_list(actions: list) -> list[dict]:
        result = []
        for a in actions:
            entry: dict[str, Any] = {
                "type": a.type,
                "params": a.params,
            }
            if a.on_reply:
                entry["on_reply"] = [
                    WebServer._serialize_trigger(t) for t in a.on_reply
                ]
            if a.on_else:
                entry["on_else"] = WebServer._serialize_action_list(a.on_else)
            result.append(entry)
        return result

    def _serialize_config(self, config: Any) -> dict:
        from alexa_custom.config import ActionsConfig

        if not isinstance(config, ActionsConfig):
            return {}

        result: dict[str, Any] = {
            "wake_words": list(config.wake_words),
            "triggers": [self._serialize_trigger(t) for t in config.triggers],
        }

        if config.recognition is not None:
            result["recognition"] = {
                "wake_window": config.recognition.wake_window,
                "matching_threshold": config.recognition.matching_threshold,
                "matching_algorithm": config.recognition.matching_algorithm,
                "reply_matching_algorithm": config.recognition.reply_matching_algorithm,
                "reply_matching_threshold": config.recognition.reply_matching_threshold,
                "follow_up": config.recognition.follow_up,
                "follow_up_timeout": config.recognition.follow_up_timeout,
                "follow_up_max_turns": config.recognition.follow_up_max_turns,
            }

        if config.stt is not None:
            result["stt"] = {
                "backend": config.stt.backend,
                "rms_threshold": config.stt.rms_threshold,
                "adaptive_rms": config.stt.adaptive_rms,
                "vad_silence_ms": config.stt.vad_silence_ms,
            }

        if config.audio is not None:
            result["audio"] = {
                "output_volume": config.audio.output_volume,
                "input_gain": config.audio.input_gain,
            }

        if config.tts is not None:
            result["tts"] = {
                "backend": config.tts.backend,
                "voice": config.tts.voice,
            }

        if config.llm is not None:
            host = config.llm.host
            display_host = (
                host.replace("https://", "").replace("http://", "").split(":")[0]
            )
            result["llm"] = {
                "enabled": True,
                "model": config.llm.model,
                "host": display_host,
                "fallback": config.llm.fallback_on_no_match,
            }

        return result

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
            loop.run_until_complete(
                run_fn(stop_threading, on_event_cb or self.on_event, livekit_stop)
            )
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

        config_obj = None
        if stt_params and "config" in stt_params:
            config_obj = stt_params["config"]
        elif self._config_manager and self._config_manager.config:
            config_obj = self._config_manager.config

        if (
            config_obj
            and hasattr(config_obj, "web")
            and hasattr(config_obj.web, "history_file")
        ):
            self._history_file = Path(config_obj.web.history_file)

        if hot_reload:
            from alexa_custom.config_manager import ConfigManager

            async def _on_source_restart():
                await self._broadcast({"type": "restarting"})

            cm = ConfigManager(None)
            cm.start_source_watcher("alexa_custom", on_restart=_on_source_restart)

        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_static("/static/", Path(__file__).parent / "static")
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_get("/api/config", self._handle_config_get)
        app.router.add_post("/api/config", self._handle_config_update)
        app.router.add_put("/api/config", self._handle_config_replace)
        app.router.add_get("/api/config/defaults", self._handle_config_defaults)
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/metrics", self._handle_metrics)
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

        all_watch = list(watch_paths or []) + [
            _DASHBOARD_PATH,
            Path(__file__).parent / "static" / "dashboard.css",
            Path(__file__).parent / "static" / "dashboard.js",
            Path(__file__).parent / "static" / "dashboard-graph.js",
            Path(__file__).parent / "static" / "dashboard-config.js",
            Path(__file__).parent / "static" / "dashboard-monitor.js",
            Path(__file__).parent / "static" / "dashboard-history.js",
        ]
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
                config=lambda: (
                    self._config_manager.config
                    if self._config_manager and self._config_manager.config is not None
                    else stt_params["config"]
                ),
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
    cpu_limit: float = 1.0,
    shutdown_callback: Callable | None = None,
    extra_event_cb: Callable | None = None,
    extra_stt_event_cb: Callable | None = None,
    conf_dir: Path = Path("conf"),
) -> None:
    server = WebServer(
        port=port,
        output_volume=output_volume,
        input_gain=input_gain,
        cpu_limit=cpu_limit,
        shutdown_callback=shutdown_callback,
        extra_event_cb=extra_event_cb,
        extra_stt_event_cb=extra_stt_event_cb,
        hot_reload=hot_reload,
        conf_dir=conf_dir,
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
        if shutdown_callback is not None:
            shutdown_callback()
