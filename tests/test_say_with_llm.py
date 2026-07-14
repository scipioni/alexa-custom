from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from alexa_custom.actions import registry
from alexa_custom.config import ActionEntry, LLMConfig
from alexa_custom.llm import _UNREACHABLE


def _action(params: dict) -> ActionEntry:
    return ActionEntry(type="say-with-llm", params=params)


def _actions_config(model: str = "test:model") -> MagicMock:
    cfg = LLMConfig(backend="ollama", host="http://localhost:11434", model=model)
    ac = MagicMock()
    ac.llm = cfg
    return ac


def _make_engine(reply: str = "Risposta di test.") -> MagicMock:
    engine = MagicMock()
    engine.reply_streaming = AsyncMock(return_value=reply)
    return engine


@pytest.mark.asyncio
async def test_basic_prompt_calls_reply_streaming():
    """prompt is sent to reply_streaming as user_text."""
    engine = _make_engine()
    tts = MagicMock()
    tts.say = MagicMock()
    with (
        patch("alexa_custom.llm.get_engine", return_value=engine) as mock_get_engine,
        patch("alexa_custom.tts.get_engine", return_value=tts),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({"prompt": "Dimmi una curiosità"}),
            actions_config=_actions_config(),
        )
        mock_get_engine.assert_called_once()
        engine.reply_streaming.assert_awaited_once()
        call_args = engine.reply_streaming.call_args
        assert call_args[0][0] == "Dimmi una curiosità"


@pytest.mark.asyncio
async def test_file_content_prepended_to_prompt():
    """File content is read and prepended to the prompt."""
    engine = _make_engine()
    tts = MagicMock()
    with (
        patch("alexa_custom.llm.get_engine", return_value=engine),
        patch("alexa_custom.tts.get_engine", return_value=tts),
        patch("builtins.open", mock_open(read_data="Contenuto del file.")),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({"file": "/fake/notes.txt", "prompt": "Riassumi"}),
            actions_config=_actions_config(),
        )
        user_text = engine.reply_streaming.call_args[0][0]
        assert user_text == "Contenuto del file.\n\nRiassumi"


@pytest.mark.asyncio
async def test_max_chars_truncates_file():
    """File content is truncated to max_chars before being sent."""
    long_content = "A" * 5000
    engine = _make_engine()
    tts = MagicMock()

    class _LimitedOpen:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def read(self, n):
            return long_content[:n]

    with (
        patch("alexa_custom.llm.get_engine", return_value=engine),
        patch("alexa_custom.tts.get_engine", return_value=tts),
        patch("builtins.open", return_value=_LimitedOpen()),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({"file": "/fake/big.txt", "max_chars": 100}),
            actions_config=_actions_config(),
        )
        user_text = engine.reply_streaming.call_args[0][0]
        assert len(user_text) == 100
        assert user_text == "A" * 100


@pytest.mark.asyncio
async def test_missing_file_continues_with_prompt_only():
    """OSError on file read is caught; action proceeds with prompt only."""
    engine = _make_engine()
    tts = MagicMock()
    with (
        patch("alexa_custom.llm.get_engine", return_value=engine),
        patch("alexa_custom.tts.get_engine", return_value=tts),
        patch("builtins.open", side_effect=OSError("not found")),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({"file": "/nonexistent.txt", "prompt": "Ciao"}),
            actions_config=_actions_config(),
        )
        user_text = engine.reply_streaming.call_args[0][0]
        assert user_text == "Ciao"


@pytest.mark.asyncio
async def test_llm_not_configured_speaks_literally():
    """When actions_config.llm is None, the text is spoken directly via TTS."""
    tts = MagicMock()
    tts.say = MagicMock()
    ac = MagicMock()
    ac.llm = None
    with patch("alexa_custom.tts.get_engine", return_value=tts):
        await registry.execute(
            "say-with-llm",
            action=_action({"prompt": "Testo diretto"}),
            actions_config=ac,
        )
        tts.say.assert_called_once()
        spoken = tts.say.call_args[0][0]
        assert spoken == "Testo diretto"


@pytest.mark.asyncio
async def test_unreachable_fallback_speaks_prompt():
    """When reply_streaming returns _UNREACHABLE, the rendered prompt is spoken."""
    engine = _make_engine(reply=_UNREACHABLE)
    tts = MagicMock()
    tts.say = MagicMock()
    with (
        patch("alexa_custom.llm.get_engine", return_value=engine),
        patch("alexa_custom.tts.get_engine", return_value=tts),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({"prompt": "Prompt di fallback"}),
            actions_config=_actions_config(),
        )
        tts.say.assert_called_once()
        spoken = tts.say.call_args[0][0]
        assert spoken == "Prompt di fallback"


@pytest.mark.asyncio
async def test_template_rendering_on_prompt():
    """_render_text is applied to prompt before sending to LLM."""
    engine = _make_engine()
    tts = MagicMock()
    # _render_text expands $(shell) placeholders; a prompt without $(...) is returned unchanged
    with (
        patch("alexa_custom.llm.get_engine", return_value=engine),
        patch("alexa_custom.tts.get_engine", return_value=tts),
        patch(
            "alexa_custom.actions._render_text",
            new=AsyncMock(return_value="rendered prompt"),
        ),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({"prompt": "$(echo rendered prompt)"}),
            actions_config=_actions_config(),
        )
        user_text = engine.reply_streaming.call_args[0][0]
        assert user_text == "rendered prompt"


@pytest.mark.asyncio
async def test_empty_prompt_and_no_file_is_noop():
    """When neither prompt nor file yields text, action completes silently."""
    engine = _make_engine()
    tts = MagicMock()
    with (
        patch("alexa_custom.llm.get_engine", return_value=engine),
        patch("alexa_custom.tts.get_engine", return_value=tts),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({}),
            actions_config=_actions_config(),
        )
        engine.reply_streaming.assert_not_awaited()
        tts.say.assert_not_called()


@pytest.mark.asyncio
async def test_model_override_uses_different_engine_key():
    """When model param is set, get_engine is called with a cfg whose model matches."""
    engine = _make_engine()
    tts = MagicMock()
    captured = {}
    def _capture_engine(cfg, lang):
        captured["model"] = cfg.model
        return engine
    with (
        patch("alexa_custom.llm.get_engine", side_effect=_capture_engine),
        patch("alexa_custom.tts.get_engine", return_value=tts),
    ):
        await registry.execute(
            "say-with-llm",
            action=_action({"prompt": "Ciao", "model": "mistral:7b"}),
            actions_config=_actions_config(model="default:model"),
        )
        assert captured["model"] == "mistral:7b"
