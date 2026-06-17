"""Tests for the persistent history JSONL logic."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from alexa_custom.web import WebServer


@pytest.fixture
def temp_history_file(tmp_path):
    return tmp_path / "history.jsonl"


@pytest.fixture
def server(temp_history_file):
    srv = WebServer()
    srv._history_file = temp_history_file
    srv._broadcast = AsyncMock()
    return srv


@pytest.mark.asyncio
class TestHistoryFileHelpers:
    async def test_append_history_log(self, server, temp_history_file):
        """Append history log helper must append a single JSON line to the file."""
        server._loop = asyncio.get_running_loop()
        data = {"session_id": "test-1", "wake": {"word": "alexa"}}
        await server._append_history_log(data)

        assert temp_history_file.exists()
        lines = temp_history_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == data

    async def test_clear_history_log(self, server, temp_history_file):
        """Clear helper must truncate the history file to size 0."""
        server._loop = asyncio.get_running_loop()
        temp_history_file.write_text('{"id": 1}\n{"id": 2}\n', encoding="utf-8")
        assert temp_history_file.stat().st_size > 0

        await server._clear_history_log()
        assert temp_history_file.exists()
        assert temp_history_file.stat().st_size == 0

    async def test_flag_history_log_fp(self, server, temp_history_file):
        """Flag FP helper must update the targeted session ID in-place in the file."""
        server._loop = asyncio.get_running_loop()
        session1 = {"session_id": "s-1", "feedback": {"false_positive": False}}
        session2 = {"session_id": "s-2", "feedback": {"false_positive": False}}

        temp_history_file.write_text(
            json.dumps(session1) + "\n" + json.dumps(session2) + "\n",
            encoding="utf-8",
        )

        await server._flag_history_log_fp("s-2")

        lines = temp_history_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

        out1 = json.loads(lines[0])
        out2 = json.loads(lines[1])

        assert out1["session_id"] == "s-1"
        assert out1["feedback"]["false_positive"] is False

        assert out2["session_id"] == "s-2"
        assert out2["feedback"]["false_positive"] is True
        assert out2["feedback"]["user_flagged"] is True

    async def test_read_last_history_entries(self, server, temp_history_file):
        """Read last entries helper must load lines in chronological order up to the limit."""
        server._loop = asyncio.get_running_loop()
        for i in range(5):
            temp_history_file.open("a", encoding="utf-8").write(
                json.dumps({"id": i}) + "\n"
            )

        entries = await server._read_last_history_entries(limit=3)
        assert len(entries) == 3
        # Should return last 3 in chronological order
        assert entries[0]["id"] == 2
        assert entries[1]["id"] == 3
        assert entries[2]["id"] == 4


@pytest.mark.asyncio
class TestSessionAggregation:
    async def test_successful_interaction_aggregation(self, server, temp_history_file):
        """A complete STT flow must aggregate and append a unified session log."""
        server._loop = asyncio.get_running_loop()
        # Initialize confidence values in _pending_vu
        server._pending_vu["confidence"] = 0.95
        server._pending_vu["mic"] = 0.15
        server._pending_vu["rms_threshold"] = 0.04

        # 1. Trigger Wake
        server._process_history_event("wake", {"word": "alexa", "timeout": 5.0})
        assert server._active_session is not None
        session_id = server._active_session["session_id"]
        assert server._active_session["wake"]["word"] == "alexa"

        # 2. Transcribe
        server._process_history_event("transcribing", {"text": "hello world"})
        assert server._active_session["transcript"]["text"] == "hello world"

        # 3. Match Action (which flushes session)
        server._process_history_event(
            "matched",
            {
                "transcript": "hello world",
                "phrase": "hello world",
                "score": 100,
                "actions": [{"type": "mqtt_publish", "params": {"topic": "test"}}],
            },
        )

        # Active session must be reset back to None
        assert server._active_session is None

        # Give a small tick for the async file task to finish appending
        await asyncio.sleep(0.01)

        # File must contain the record
        assert temp_history_file.exists()
        lines = temp_history_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])

        assert record["session_id"] == session_id
        assert record["wake"]["word"] == "alexa"
        assert record["transcript"]["text"] == "hello world"
        assert record["transcript"]["is_matched"] is True
        assert record["action"]["type"] == "mqtt_publish"

        # Broadcast must be called with the unified history_item packet
        server._broadcast.assert_called_once()
        b_msg = server._broadcast.call_args[0][0]
        assert b_msg["type"] == "history_item"
        assert b_msg["session"]["session_id"] == session_id

    async def test_clear_discards_active_session_and_new_session_appends(
        self, server, temp_history_file
    ):
        """Clearing history must discard the in-progress session and allow new sessions."""
        server._loop = asyncio.get_running_loop()
        server._pending_vu["confidence"] = 0.9

        # Start a session without completing it
        server._process_history_event("wake", {"word": "alexa"})
        assert server._active_session is not None

        # Clear history mid-session (as _handle_control does)
        await server._clear_history_log()
        server._active_session = None
        server._broadcast.reset_mock()

        # A lingering listening event from the previous dispatch must be a no-op
        server._process_history_event("listening", {})
        await asyncio.sleep(0.01)
        # File should not exist or be empty — the discarded session must not have been written
        assert not temp_history_file.exists() or temp_history_file.stat().st_size == 0
        server._broadcast.assert_not_called()

        # New session after the clear must be appended and broadcast
        server._process_history_event("wake", {"word": "alexa"})
        server._process_history_event(
            "matched",
            {
                "transcript": "new command",
                "phrase": "new command",
                "score": 90,
                "actions": [{"type": "mqtt_publish"}],
            },
        )
        await asyncio.sleep(0.01)

        lines = temp_history_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["transcript"]["text"] == "new command"

        server._broadcast.assert_called_once()
        msg = server._broadcast.call_args[0][0]
        assert msg["type"] == "history_item"
        assert msg["session"]["transcript"]["text"] == "new command"

    async def test_gated_false_trigger_aggregation(self, server, temp_history_file):
        """A wake word followed by a gating event must record a false trigger."""
        server._loop = asyncio.get_running_loop()
        server._pending_vu["mic"] = 0.08
        server._process_history_event("wake", {"word": "galileo"})
        session_id = server._active_session["session_id"]

        server._process_history_event("gated", {})

        assert server._active_session is None
        await asyncio.sleep(0.01)

        lines = temp_history_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])

        assert record["session_id"] == session_id
        assert record["transcript"]["text"] == ""
        assert record["transcript"]["is_matched"] is False
        assert record["diagnostics"]["gated"] is True

    async def test_direct_command_aggregation(self, server, temp_history_file):
        """A direct command match (no wake event) must aggregate and append a session log."""
        server._loop = asyncio.get_running_loop()
        server._pending_vu["mic"] = 0.12
        server._pending_vu["rms_threshold"] = 0.04

        # Simulate a direct command "matched" event without any preceding "wake" event
        server._process_history_event(
            "matched",
            {
                "transcript": "che ore sono",
                "phrase": "che ore sono",
                "score": 100,
                "actions": [{"type": "tts_say", "params": {"text": "Sono le 21"}}],
            },
        )

        assert server._active_session is None
        await asyncio.sleep(0.01)

        assert temp_history_file.exists()
        lines = temp_history_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])

        assert record["wake"]["word"] == ""
        assert record["transcript"]["text"] == "che ore sono"
        assert record["transcript"]["is_matched"] is True
        assert record["action"]["type"] == "tts_say"

