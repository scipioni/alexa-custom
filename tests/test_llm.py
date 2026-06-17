"""Tests for llm.py: OllamaClient, ConversationEngine, ToolRegistry, tool-calling."""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alexa_custom.config import ActionEntry, LLMConfig, Trigger
from alexa_custom.llm import (
    ActionsFileStore,
    ConversationEngine,
    LearnWizard,
    OllamaClient,
    OllamaUnreachable,
    ToolRegistry,
    ToolSchema,
    _UNREACHABLE,
    _parse_tool_call,
    _split_sentences,
    _tool_get_datetime,
    _tool_set_volume,
    _tool_shell,
    build_default_tool_registry,
    get_engine,
    normalize_confirm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_llm_config(**kwargs) -> LLMConfig:
    defaults = dict(
        backend="ollama",
        host="http://localhost:11434",
        model="llama3.2",
        context_turns=4,
        context_window_secs=60,
        fallback_on_no_match=True,
        learn_commands=True,
        request_timeout=5.0,
    )
    defaults.update(kwargs)
    return LLMConfig(**defaults)


def _fake_stream(*responses):
    """Return a chat_stream replacement that yields each response as one token."""
    it = iter(responses)

    async def stream(messages, model):
        yield next(it, "ok.")

    return stream


def _failing_stream(exc):
    """Return a chat_stream replacement that raises exc immediately."""

    async def stream(messages, model):
        raise exc
        yield  # pragma: no cover — makes this an async generator

    return stream


async def _noop_say(text: str) -> None:
    pass


# ---------------------------------------------------------------------------
# _split_sentences tests
# ---------------------------------------------------------------------------


class TestSplitSentences:
    def test_basic_split_on_period(self):
        sentences, rem = _split_sentences("Ciao. Come stai?")
        assert sentences == ["Ciao.", "Come stai?"]
        assert rem == ""

    def test_period_alone_splits(self):
        sentences, rem = _split_sentences("Ciao.")
        assert sentences == ["Ciao."]
        assert rem == ""

    def test_split_on_exclamation(self):
        sentences, rem = _split_sentences("Benvenuto! Prego.")
        assert sentences == ["Benvenuto!", "Prego."]
        assert rem == ""

    def test_no_split_on_decimal_number(self):
        # decimal period must not split the sentence; final period ends it normally
        sentences, rem = _split_sentences("La temperatura è 10.5 gradi.")
        assert sentences == ["La temperatura è 10.5 gradi."]
        assert rem == ""

    def test_no_split_on_lowercase_continuation(self):
        # period followed by lowercase is treated as mid-sentence (e.g. abbreviation)
        sentences, rem = _split_sentences("Sto parlando con il dr. stefano.")
        assert sentences == ["Sto parlando con il dr. stefano."]
        assert rem == ""

    def test_multiple_sentences(self):
        sentences, rem = _split_sentences("Prima frase. Seconda frase. Terza")
        assert len(sentences) == 2
        assert sentences[0] == "Prima frase."
        assert sentences[1] == "Seconda frase."
        assert rem == "Terza"

    def test_remainder_when_no_terminal_punct(self):
        sentences, rem = _split_sentences("Frase incompleta")
        assert sentences == []
        assert rem == "Frase incompleta"


# ---------------------------------------------------------------------------
# get_engine cache key tests
# ---------------------------------------------------------------------------


class TestGetEngineCache:
    def test_same_config_returns_same_engine(self):
        cfg = make_llm_config()
        e1 = get_engine(cfg, "it-IT")
        e2 = get_engine(cfg, "it-IT")
        assert e1 is e2

    def test_different_system_prompt_returns_new_engine(self):
        cfg1 = make_llm_config(system_prompt=None)
        cfg2 = make_llm_config(system_prompt="Sei un robot.")
        e1 = get_engine(cfg1, "it-IT")
        e2 = get_engine(cfg2, "it-IT")
        assert e1 is not e2

    def test_different_timeout_returns_new_engine(self):
        cfg1 = make_llm_config(request_timeout=5.0)
        cfg2 = make_llm_config(request_timeout=30.0)
        e1 = get_engine(cfg1, "it-IT")
        e2 = get_engine(cfg2, "it-IT")
        assert e1 is not e2


# ---------------------------------------------------------------------------
# OllamaClient tests
# ---------------------------------------------------------------------------


class TestOllamaClient:
    @pytest.mark.asyncio
    async def test_successful_chat(self):
        client = OllamaClient("http://localhost:11434", timeout=5.0)
        client.chat_stream = _fake_stream("Ciao!")
        result = await client.chat([{"role": "user", "content": "ciao"}], "llama3.2")
        assert result == "Ciao!"

    @pytest.mark.asyncio
    async def test_chat_concatenates_tokens(self):
        client = OllamaClient("http://localhost:11434", timeout=5.0)

        async def multi_token(messages, model):
            yield "Ci"
            yield "ao"
            yield "!"

        client.chat_stream = multi_token
        result = await client.chat([], "llama3.2")
        assert result == "Ciao!"

    @pytest.mark.asyncio
    async def test_connect_error_raises_unreachable(self):
        client = OllamaClient("http://localhost:11434", timeout=5.0)
        client.chat_stream = _failing_stream(OllamaUnreachable("refused"))
        with pytest.raises(OllamaUnreachable):
            await client.chat([], "llama3.2")

    @pytest.mark.asyncio
    async def test_timeout_raises_unreachable(self):
        client = OllamaClient("http://localhost:11434", timeout=5.0)
        client.chat_stream = _failing_stream(OllamaUnreachable("timeout"))
        with pytest.raises(OllamaUnreachable):
            await client.chat([], "llama3.2")

    @pytest.mark.asyncio
    async def test_non_2xx_raises_unreachable(self):
        client = OllamaClient("http://localhost:11434", timeout=5.0)
        client.chat_stream = _failing_stream(OllamaUnreachable("HTTP 500"))
        with pytest.raises(OllamaUnreachable):
            await client.chat([], "llama3.2")

    @pytest.mark.asyncio
    @patch("alexa_custom.llm.httpx.AsyncClient")
    async def test_chat_stream_handles_httpx_timeout(self, mock_client_class):
        import httpx

        mock_client = MagicMock()
        mock_client.stream.side_effect = httpx.TimeoutException("mocked timeout")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        client = OllamaClient("http://localhost:11434", timeout=5.0)
        with pytest.raises(OllamaUnreachable) as exc_info:
            async for _ in client.chat_stream([], "model"):
                pass
        assert "Ollama timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch("alexa_custom.llm.httpx.AsyncClient")
    async def test_chat_stream_handles_httpx_http_error(self, mock_client_class):
        import httpx

        mock_client = MagicMock()
        mock_client.stream.side_effect = httpx.HTTPError("mocked http error")
        mock_client_class.return_value.__aenter__.return_value = mock_client

        client = OllamaClient("http://localhost:11434", timeout=5.0)
        with pytest.raises(OllamaUnreachable) as exc_info:
            async for _ in client.chat_stream([], "model"):
                pass
        assert "Ollama HTTP error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ConversationEngine tests
# ---------------------------------------------------------------------------


class TestConversationEngine:
    def _make_engine(self, **kwargs) -> ConversationEngine:
        cfg = make_llm_config(**kwargs)
        return ConversationEngine(cfg, lang="it-IT")

    @pytest.mark.asyncio
    async def test_reply_returns_text(self):
        engine = self._make_engine()
        engine._client.chat_stream = _fake_stream("Risposta.")
        spoken: list[str] = []

        async def say_fn(t: str) -> None:
            spoken.append(t)

        result = await engine.reply_streaming("Ciao", say_fn)
        assert result == "Risposta."
        assert spoken == ["Risposta."]

    @pytest.mark.asyncio
    async def test_reply_streaming_multi_sentence(self):
        engine = self._make_engine()

        async def stream(messages, model):
            yield "Prima frase. Seconda frase."

        engine._client.chat_stream = stream
        spoken: list[str] = []

        async def say_fn(t: str) -> None:
            spoken.append(t)

        result = await engine.reply_streaming("test", say_fn)
        assert len(spoken) == 2
        assert "Prima frase." in spoken[0]
        assert "Seconda frase." in spoken[1]
        assert "Prima frase." in result
        assert "Seconda frase." in result

    @pytest.mark.asyncio
    async def test_history_accumulates(self):
        engine = self._make_engine()

        async def stream(messages, model):
            yield "ok."

        engine._client.chat_stream = stream
        await engine.reply_streaming("messaggio uno", _noop_say)
        await engine.reply_streaming("messaggio due", _noop_say)
        assert len(engine._history) == 4  # 2 user + 2 assistant

    @pytest.mark.asyncio
    async def test_history_capped_at_context_turns(self):
        engine = self._make_engine(context_turns=2)

        async def stream(messages, model):
            yield "ok."

        engine._client.chat_stream = stream
        for i in range(5):
            await engine.reply_streaming(f"msg {i}", _noop_say)
        assert len(engine._history) <= 4  # context_turns * 2

    @pytest.mark.asyncio
    async def test_history_reset_after_context_window(self):
        engine = self._make_engine(context_window_secs=1)

        async def stream(messages, model):
            yield "ok."

        engine._client.chat_stream = stream
        await engine.reply_streaming("primo", _noop_say)
        assert len(engine._history) == 2
        engine._last_ts = time.monotonic() - 2  # simulate 2 s elapsed
        await engine.reply_streaming("secondo", _noop_say)
        assert len(engine._history) == 2  # reset: only the new exchange

    @pytest.mark.asyncio
    async def test_unreachable_returns_sentinel(self):
        engine = self._make_engine()
        engine._client.chat_stream = _failing_stream(OllamaUnreachable("down"))
        result = await engine.reply_streaming("ciao", _noop_say)
        assert result == _UNREACHABLE

    @pytest.mark.asyncio
    async def test_system_prompt_override(self):
        engine = self._make_engine(system_prompt="Tu sei un robot.")
        captured: list[dict] = []

        async def stream(messages, model):
            captured.extend(messages)
            yield "ok."

        engine._client.chat_stream = stream
        await engine.reply_streaming("test", _noop_say)
        assert captured[0]["role"] == "system"
        assert captured[0]["content"] == "Tu sei un robot."

    @pytest.mark.asyncio
    async def test_reply_streaming_timeout(self):
        import asyncio

        engine = self._make_engine(request_timeout=0.01)

        async def slow_stream(messages, model):
            await asyncio.sleep(0.05)
            yield "this should not be reached"

        engine._client.chat_stream = slow_stream
        result = await engine.reply_streaming("test", _noop_say)
        assert result == _UNREACHABLE
        assert len(engine._history) == 0  # history pop/cleared


# ---------------------------------------------------------------------------
# ActionsFileStore tests
# ---------------------------------------------------------------------------


class TestActionsFileStore:
    def test_append_trigger_global(self, tmp_path):
        af = tmp_path / "actions.yaml"
        trigger = Trigger(
            phrase="buonanotte",
            actions=[ActionEntry(type="say", params={"text": "Buonanotte!"})],
        )
        ActionsFileStore.append_trigger(af, trigger, wake_word=None)
        assert af.exists()
        content = af.read_text()
        assert "buonanotte" in content
        assert "say" in content

    def test_append_trigger_wake_word(self, tmp_path):
        af = tmp_path / "actions.yaml"
        trigger = Trigger(
            phrase="ciao",
            actions=[ActionEntry(type="log", params={"message": "hi"})],
        )
        ActionsFileStore.append_trigger(af, trigger, wake_word="galileo")
        content = af.read_text()
        assert "galileo" in content
        assert "ciao" in content

    def test_separator_inserted_on_first_learned_command(self, tmp_path):
        af = tmp_path / "actions.yaml"
        af.write_text(
            "triggers:\n  - phrase: existing\n    actions:\n      - type: log\n        message: x\n"
        )
        trigger = Trigger(
            phrase="nuovo",
            actions=[ActionEntry(type="log", params={"message": "new"})],
        )
        ActionsFileStore.append_trigger(af, trigger)
        content = af.read_text()
        assert "--- learned commands ---" in content

    def test_atomic_write(self, tmp_path):
        p = tmp_path / "test.yaml"
        ActionsFileStore.save(p, "triggers: []\n")
        assert p.exists()
        assert not (tmp_path / "test.yaml.tmp").exists()
        assert p.read_text() == "triggers: []\n"

    def test_round_trip_preserves_content(self, tmp_path):
        af = tmp_path / "actions.yaml"
        original = "# my comment\ntriggers:\n  - phrase: test\n    actions:\n      - type: log\n        message: ok\n"
        af.write_text(original)
        trigger = Trigger(
            phrase="nuovo",
            actions=[ActionEntry(type="tone", params={"name": "info"})],
        )
        ActionsFileStore.append_trigger(af, trigger)
        content = af.read_text()
        assert "test" in content
        assert "nuovo" in content


# ---------------------------------------------------------------------------
# normalize_confirm tests
# ---------------------------------------------------------------------------


class TestNormalizeConfirm:
    def test_si_is_yes(self):
        assert normalize_confirm("sì") == "yes"
        assert normalize_confirm("si") == "yes"

    def test_no_is_no(self):
        assert normalize_confirm("no") == "no"
        assert normalize_confirm("annulla") == "no"

    def test_empty_defaults_to_no(self):
        assert normalize_confirm("") == "no"
        assert normalize_confirm("boh") == "no"

    def test_substring_does_not_false_positive(self):
        # "si" is a substring of "sicuro" and "no" of "non" — a substring match
        # would read this as "yes"; token matching must not.
        assert normalize_confirm("non sicuro") == "no"

    def test_multiword_no_phrase(self):
        assert normalize_confirm("no grazie") == "no"

    def test_yes_with_extra_words(self):
        assert normalize_confirm("sì certo") == "yes"


# ---------------------------------------------------------------------------
# LearnWizard integration test
# ---------------------------------------------------------------------------


class TestLearnWizard:
    @pytest.mark.asyncio
    async def test_single_action_command_saved(self, tmp_path):
        af = tmp_path / "actions.yaml"
        cfg = make_llm_config()

        spoken: list[str] = []
        listened = iter(
            ["buonanotte", "dire buonanotte a tutti", "buonanotte a tutti", "sì"]
        )

        async def say_fn(text: str) -> None:
            spoken.append(text)

        async def listen_fn(timeout: float) -> str:
            return next(listened, "")

        with patch(
            "alexa_custom.llm.OllamaClient.chat",
            new=AsyncMock(return_value="say"),
        ):
            wizard = LearnWizard(
                cfg, lang="it-IT", actions_file_path=af, wake_word="galileo"
            )
            trigger = await wizard.run(listen_fn, say_fn)

        assert trigger is not None
        assert trigger.phrase == "buonanotte"
        assert len(trigger.actions) == 1
        assert trigger.actions[0].type == "say"
        assert af.exists()

    @pytest.mark.asyncio
    async def test_cancel_on_no_confirmation(self, tmp_path):
        af = tmp_path / "actions.yaml"
        cfg = make_llm_config()
        listened = iter(["buonanotte", "dire qualcosa", "ciao", "no"])

        async def say_fn(text: str) -> None:
            pass

        async def listen_fn(timeout: float) -> str:
            return next(listened, "")

        with patch(
            "alexa_custom.llm.OllamaClient.chat",
            new=AsyncMock(return_value="say"),
        ):
            wizard = LearnWizard(cfg, lang="it-IT", actions_file_path=af)
            trigger = await wizard.run(listen_fn, say_fn)

        assert trigger is None
        assert not af.exists()


# ---------------------------------------------------------------------------
# ToolRegistry tests
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_register_and_list(self):
        registry = ToolRegistry()
        schema = ToolSchema(
            name="test_tool",
            description="A test tool.",
            parameters=[],
            handler=AsyncMock(return_value={"success": True, "output": "ok"}),
        )
        registry.register(schema)
        assert registry.get("test_tool") is schema
        assert registry.get("unknown") is None
        assert len(registry.list_schemas()) == 1

    def test_to_system_prompt_block_contains_tool_name(self):
        registry = ToolRegistry()
        registry.register(ToolSchema(
            name="get_datetime",
            description="Returns the current date and time.",
            parameters=[],
            handler=AsyncMock(),
        ))
        block = registry.to_system_prompt_block()
        assert "get_datetime" in block
        assert "<tool_call>" in block

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        result = await registry.execute("nope", {})
        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_calls_handler(self):
        registry = ToolRegistry()
        handler = AsyncMock(return_value={"success": True, "output": "done"})
        registry.register(ToolSchema(
            name="test", description="", parameters=[], handler=handler,
        ))
        result = await registry.execute("test", {})
        assert result["success"] is True
        assert result["output"] == "done"
        handler.assert_awaited_once_with()


# ---------------------------------------------------------------------------
# _parse_tool_call tests
# ---------------------------------------------------------------------------


class TestParseToolCall:
    def test_parse_valid_call(self):
        text = '<tool_call>\n{"name": "shell", "arguments": {"command": "echo hi"}}\n</tool_call>'
        call = _parse_tool_call(text)
        assert call is not None
        assert call.name == "shell"
        assert call.arguments == {"command": "echo hi"}

    def test_parse_no_tool_call(self):
        assert _parse_tool_call("Ciao, questo è un messaggio normale.") is None

    def test_parse_malformed_json(self):
        text = "<tool_call>\n{invalid\n</tool_call>"
        assert _parse_tool_call(text) is None

    def test_parse_missing_arguments(self):
        text = '<tool_call>\n{"name": "test"}\n</tool_call>'
        assert _parse_tool_call(text) is None

    def test_parse_multiple_blocks_returns_first(self):
        text = (
            '<tool_call>\n{"name": "first", "arguments": {} }\n</tool_call>\n'
            '<tool_call>\n{"name": "second", "arguments": {} }\n</tool_call>'
        )
        call = _parse_tool_call(text)
        assert call is not None
        assert call.name == "first"


# ---------------------------------------------------------------------------
# Tool handler tests
# ---------------------------------------------------------------------------


class TestToolGetDatetime:
    @pytest.mark.asyncio
    async def test_returns_valid_datetime(self):
        result = await _tool_get_datetime()
        assert result["success"] is True
        assert "datetime" in result["output"]
        assert "timezone" in result["output"]
        assert "weekday" in result["output"]
        # Verify ISO format
        datetime.fromisoformat(result["output"]["datetime"])


class TestToolSetVolume:
    @pytest.mark.asyncio
    async def test_rejects_non_integer(self):
        result = await _tool_set_volume(value=50.5)
        assert result["success"] is False
        assert "integer" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_clamps_below_zero(self):
        with patch("alexa_custom.audio_hw.pulse_session") as mock_pulse, \
             patch("alexa_custom.audio_hw.save_volume_config") as _sv, \
             patch("alexa_custom.audio_hw.set_output_volume") as _so:
            mock_pulse.return_value.__enter__.return_value = None
            result = await _tool_set_volume(value=-10)
        assert result["success"] is True
        assert "0%" in result["output"]

    @pytest.mark.asyncio
    async def test_clamps_above_100(self):
        with patch("alexa_custom.audio_hw.pulse_session") as mock_pulse, \
             patch("alexa_custom.audio_hw.save_volume_config") as _sv, \
             patch("alexa_custom.audio_hw.set_output_volume") as _so:
            mock_pulse.return_value.__enter__.return_value = None
            result = await _tool_set_volume(value=200)
        assert result["success"] is True
        assert "100%" in result["output"]


class TestToolShell:
    @pytest.mark.asyncio
    async def test_rejects_non_whitelisted(self):
        result = await _tool_shell("rm -rf /", whitelist=["echo ", "cat "])
        assert result["success"] is False
        assert "non consentito" in result["error"] or "whitelist" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_executes_whitelisted(self):
        result = await _tool_shell("echo hello world", whitelist=["echo "])
        assert result["success"] is True
        assert result["output"] == "hello world"

    @pytest.mark.asyncio
    async def test_empty_whitelist_blocks_all(self):
        result = await _tool_shell("echo test", whitelist=[])
        assert result["success"] is False


# ---------------------------------------------------------------------------
# ConversationEngine reply_agentic tests
# ---------------------------------------------------------------------------


class TestConversationEngineAgentic:
    def _make_engine(self, **kwargs) -> ConversationEngine:
        defaults = dict(
            backend="ollama",
            host="http://localhost:11434",
            model="llama3.2",
            context_turns=4,
            context_window_secs=60,
            request_timeout=5.0,
            tool_calling=True,
            max_tool_cycles=5,
        )
        defaults.update(kwargs)
        return ConversationEngine(LLMConfig(**defaults), lang="it-IT")

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_directly(self):
        engine = self._make_engine()
        engine._client.chat = AsyncMock(return_value="Risposta diretta.")
        registry = build_default_tool_registry()

        result = await engine.reply_agentic("Ciao", registry)

        assert result == "Risposta diretta."
        assert len(engine._history) == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_single_tool_call_then_answer(self):
        engine = self._make_engine()
        responses = iter([
            '<tool_call>\n{"name": "get_datetime", "arguments": {}}\n</tool_call>',
            "Oggi è una bella giornata.",
        ])
        engine._client.chat = AsyncMock(side_effect=lambda m, model: next(responses))
        registry = build_default_tool_registry()

        result = await engine.reply_agentic("Che giorno è?", registry)

        assert "bella giornata" in result
        assert len(engine._history) == 2

    @pytest.mark.asyncio
    async def test_max_cycles_exhausted(self):
        engine = self._make_engine(max_tool_cycles=2)
        tool_call = '<tool_call>\n{"name": "get_datetime", "arguments": {}}\n</tool_call>'
        engine._client.chat = AsyncMock(return_value=tool_call)
        registry = build_default_tool_registry()

        result = await engine.reply_agentic("test", registry, max_cycles=2)

        assert "non sono riuscito" in result or "sorry" in result.lower()
        assert engine._client.chat.await_count == 2

    @pytest.mark.asyncio
    async def test_unknown_tool_skipped(self):
        engine = self._make_engine()
        responses = iter([
            '<tool_call>\n{"name": "nonexistent", "arguments": {}}\n</tool_call>',
            "Risposta finale.",
        ])
        engine._client.chat = AsyncMock(side_effect=lambda m, model: next(responses))
        registry = build_default_tool_registry()

        result = await engine.reply_agentic("test", registry)

        assert result == "Risposta finale."

    @pytest.mark.asyncio
    async def test_unreachable_returns_sentinel(self):
        engine = self._make_engine()
        engine._client.chat = AsyncMock(side_effect=OllamaUnreachable("down"))
        registry = build_default_tool_registry()

        result = await engine.reply_agentic("test", registry)

        assert result == _UNREACHABLE
        assert len(engine._history) == 0


# ---------------------------------------------------------------------------
# build_default_tool_registry tests
# ---------------------------------------------------------------------------


class TestBuildDefaultToolRegistry:
    def test_registers_all_five_tools(self):
        registry = build_default_tool_registry()
        names = {s.name for s in registry.list_schemas()}
        assert names == {"shell", "mqtt_publish", "set_volume", "get_state", "get_datetime"}

    def test_parameters_have_constraints(self):
        registry = build_default_tool_registry()
        shell_schema = registry.get("shell")
        assert shell_schema is not None
        assert len(shell_schema.parameters) == 1
        assert shell_schema.parameters[0].name == "command"

        vol_schema = registry.get("set_volume")
        assert vol_schema is not None
        param = vol_schema.parameters[0]
        assert param.minimum == 0
        assert param.maximum == 100

        state_schema = registry.get("get_state")
        assert state_schema is not None
        assert state_schema.parameters[0].enum is not None


# ---------------------------------------------------------------------------
# End-to-end smoke test (requires live audio/STT; skipped in CI)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="requires live audio and STT; run manually on target board")
def test_e2e_llm_fallback_smoke():
    """Verify info tone plays and ConversationEngine.reply_streaming is called on nomatch."""
    pass
