"""Tests for llm.py: OllamaClient, ConversationEngine, ActionsFileStore, LearnWizard."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alexa_custom.config import ActionEntry, LLMConfig, Trigger
from alexa_custom.llm import (
    ActionsFileStore,
    ConversationEngine,
    LearnWizard,
    OllamaClient,
    OllamaUnreachable,
    _UNREACHABLE,
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


# ---------------------------------------------------------------------------
# OllamaClient tests (task 4.3)
# ---------------------------------------------------------------------------


class TestOllamaClient:
    @pytest.mark.asyncio
    async def test_successful_chat(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": {"content": "Ciao!"}}

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            client = OllamaClient("http://localhost:11434", timeout=5.0)
            result = await client.chat(
                [{"role": "user", "content": "ciao"}], "llama3.2"
            )
        assert result == "Ciao!"

    @pytest.mark.asyncio
    async def test_connect_error_raises_unreachable(self):
        import httpx

        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            client = OllamaClient("http://localhost:11434", timeout=5.0)
            with pytest.raises(OllamaUnreachable):
                await client.chat([], "llama3.2")

    @pytest.mark.asyncio
    async def test_timeout_raises_unreachable(self):
        import httpx

        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=httpx.TimeoutException("timeout")),
        ):
            client = OllamaClient("http://localhost:11434", timeout=5.0)
            with pytest.raises(OllamaUnreachable):
                await client.chat([], "llama3.2")

    @pytest.mark.asyncio
    async def test_non_2xx_raises_unreachable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            client = OllamaClient("http://localhost:11434", timeout=5.0)
            with pytest.raises(OllamaUnreachable):
                await client.chat([], "llama3.2")


# ---------------------------------------------------------------------------
# ConversationEngine tests (task 5.4)
# ---------------------------------------------------------------------------


class TestConversationEngine:
    def _make_engine(self, **kwargs) -> ConversationEngine:
        cfg = make_llm_config(**kwargs)
        return ConversationEngine(cfg, lang="it-IT")

    @pytest.mark.asyncio
    async def test_reply_returns_text(self):
        engine = self._make_engine()
        engine._client.chat = AsyncMock(return_value="Risposta")
        result = await engine.reply("Ciao")
        assert result == "Risposta"

    @pytest.mark.asyncio
    async def test_history_accumulates(self):
        engine = self._make_engine()
        engine._client.chat = AsyncMock(return_value="ok")
        await engine.reply("messaggio uno")
        await engine.reply("messaggio due")
        assert len(engine._history) == 4  # 2 user + 2 assistant

    @pytest.mark.asyncio
    async def test_history_capped_at_context_turns(self):
        engine = self._make_engine(context_turns=2)
        engine._client.chat = AsyncMock(return_value="ok")
        for i in range(5):
            await engine.reply(f"msg {i}")
        assert len(engine._history) <= 4  # context_turns * 2

    @pytest.mark.asyncio
    async def test_history_reset_after_context_window(self):
        engine = self._make_engine(context_window_secs=1)
        engine._client.chat = AsyncMock(return_value="ok")
        await engine.reply("primo")
        assert len(engine._history) == 2
        engine._last_ts = time.monotonic() - 2  # simulate 2s elapsed
        await engine.reply("secondo")
        assert len(engine._history) == 2  # reset: only the new exchange

    @pytest.mark.asyncio
    async def test_unreachable_returns_sentinel(self):
        engine = self._make_engine()
        engine._client.chat = AsyncMock(side_effect=OllamaUnreachable("down"))
        result = await engine.reply("ciao")
        assert result == _UNREACHABLE

    @pytest.mark.asyncio
    async def test_system_prompt_override(self):
        engine = self._make_engine(system_prompt="Tu sei un robot.")
        captured = []

        async def mock_chat(messages, model):
            captured.extend(messages)
            return "ok"

        engine._client.chat = mock_chat
        await engine.reply("test")
        assert captured[0]["role"] == "system"
        assert captured[0]["content"] == "Tu sei un robot."


# ---------------------------------------------------------------------------
# ActionsFileStore tests (task 3.5)
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


# ---------------------------------------------------------------------------
# LearnWizard integration test (task 6.7)
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

        # Mock OllamaClient.chat to return action type
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
# Task 10.3 — end-to-end smoke test
# Requires live audio/STT infrastructure; marked skip for CI.
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="requires live audio and STT; run manually on target board")
def test_e2e_llm_fallback_smoke():
    """Verify info tone plays and ConversationEngine.reply is called on nomatch."""
    pass
