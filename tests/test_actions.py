import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from alexa_custom.actions import (
    ActionRegistry,
    _run_action,
    italian_phonetic,
    match_trigger,
)
from alexa_custom.config import ActionEntry, Trigger


# ── italian_phonetic() ───────────────────────────────────────────────────────


class TestItalianPhonetic:
    def test_geminate_reduction(self):
        assert italian_phonetic("bello") == "belo"
        assert italian_phonetic("pazzo") == "pazo"

    def test_ch_before_e(self):
        assert italian_phonetic("che") == "ke"

    def test_ch_before_i(self):
        assert italian_phonetic("chi") == "ki"

    def test_gli_trigraph(self):
        assert italian_phonetic("figlio") == "filio"

    def test_gn_digraph(self):
        assert italian_phonetic("gnomo") == "nomo"

    def test_qu_rewrite(self):
        assert italian_phonetic("quando") == "kando"

    def test_diacritic_passthrough(self):
        # diacritics are stripped by normalize_text; no phonetic rule changes 'si'
        assert italian_phonetic("sì") == "si"

    def test_idempotent(self):
        result = italian_phonetic("chiama")
        assert italian_phonetic(result) == result


# ── match_trigger() ───────────────────────────────────────────────────────────


def _trigger(phrase: str) -> Trigger:
    return Trigger(phrase=phrase, actions=[])


class TestMatchTrigger:
    def test_exact_match(self):
        triggers = [_trigger("chiama")]
        assert match_trigger("chiama", triggers) is not None

    def test_extra_words_around_trigger(self):
        # "mi chiama" should match trigger "chiama" via token_set_ratio
        triggers = [_trigger("chiama")]
        assert match_trigger("mi chiama", triggers) is not None

    def test_phonetic_variant_match(self):
        # "ke fai" and "che fai" normalize to the same phonetic form
        triggers = [_trigger("che fai")]
        assert match_trigger("ke fai", triggers) is not None

    def test_below_threshold_miss(self):
        triggers = [_trigger("chiama")]
        assert match_trigger("xyz", triggers) is None

    def test_selects_best_trigger(self):
        triggers = [_trigger("chiama"), _trigger("saluta")]
        result = match_trigger("chiama", triggers)
        assert result is not None
        assert result.phrase == "chiama"


# ── existing registry tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_action_registry_registration():
    registry = ActionRegistry()
    mock_handler = AsyncMock()

    @registry.register("test_action")
    async def handle_test(action, **kwargs):
        await mock_handler(action, **kwargs)

    action = ActionEntry(type="test_action", params={"foo": "bar"})
    await registry.execute("test_action", action=action, extra="data")

    mock_handler.assert_called_once_with(action, extra="data")


@pytest.mark.asyncio
async def test_action_registry_unknown_action():
    registry = ActionRegistry()
    # Should not raise exception, just log warning
    await registry.execute("unknown")


@pytest.mark.asyncio
async def test_run_action_dispatch():
    mock_action = ActionEntry(type="log", params={"message": "hello"})

    with patch(
        "alexa_custom.actions.registry.execute", new_callable=AsyncMock
    ) as mock_execute:
        await _run_action(
            mock_action,
            telegram_client=MagicMock(),
            livekit_connect_fn=AsyncMock(),
            livekit_connected=False,
        )

        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        assert args[0] == "log"
        assert kwargs["action"] == mock_action
