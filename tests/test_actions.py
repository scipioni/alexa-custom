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


# ── configurable matching tests ──────────────────────────────────────────────


class TestConfigurableMatching:
    def test_levenshtein_distance(self):
        from alexa_custom.actions import levenshtein_distance
        assert levenshtein_distance("si", "si") == 0
        assert levenshtein_distance("si", "se") == 1
        assert levenshtein_distance("si", "si grazie") == 7
        assert levenshtein_distance("ciao", "miao") == 1
        assert levenshtein_distance("", "abc") == 3

    def test_get_similarity_score_all_algorithms(self):
        from alexa_custom.actions import get_similarity_score
        # 1. levenshtein similarity
        assert get_similarity_score("ciao", "miao", "levenshtein") == 75.0  # (1 - 1/4) * 100
        assert get_similarity_score("si", "si", "levenshtein") == 100.0

        # 2. ratio similarity
        assert get_similarity_score("si", "si", "ratio") == 100.0

        # 3. token_set_ratio similarity
        assert get_similarity_score("si", "si", "token_set_ratio") == 100.0

    def test_match_trigger_with_custom_algorithms_and_thresholds(self):
        triggers = [_trigger("accendi la luce")]

        # token_set_ratio is tolerant to word ordering & extra words
        assert match_trigger("luce accendi la", triggers, threshold=80, algorithm="token_set_ratio") is not None

        # levenshtein is strict about character alignment and sequence
        assert match_trigger("luce accendi la", triggers, threshold=80, algorithm="levenshtein") is None

    def test_short_phrase_exact_match_guard(self):
        # Trigger phrase "si" has length 2 (< 4)
        triggers = [_trigger("si")]

        for algo in ["token_set_ratio", "levenshtein", "ratio"]:
            # Exact match must succeed
            assert match_trigger("si", triggers, algorithm=algo) is not None
            # Inflected or different words must fail
            assert match_trigger("se", triggers, algorithm=algo) is None
            # Extra words must fail even for token_set_ratio!
            assert match_trigger("si grazie", triggers, algorithm=algo) is None

    @pytest.mark.asyncio
    async def test_reply_matching_independence(self):
        from alexa_custom.config import RecognitionConfig
        # Mock ActionsConfig
        config = MagicMock()
        config.recognition = RecognitionConfig(
            matching_algorithm="token_set_ratio",
            matching_threshold=70.0,
            reply_matching_algorithm="levenshtein",
            reply_matching_threshold=90.0,
        )

        from alexa_custom.actions import handle_ask
        action = ActionEntry(
            type="ask",
            params={"text": "vuoi?", "timeout": 1.0},
        )
        action.on_reply = [Trigger(phrase="chiama", actions=[])]

        # Mock listen_fn to return a partial match "chiamare" (dist = 2, max_len = 8)
        # score = (1 - 2/8) * 100 = 75.0%
        # Under levenshtein threshold of 90.0, "chiamare" should fail to match "chiama"!
        mock_listen_fn = AsyncMock(return_value="chiamare")

        with patch("alexa_custom.actions.dispatch", new_callable=AsyncMock) as mock_dispatch:
            with patch("alexa_custom.tts.get_engine"):
                await handle_ask(
                    action,
                    telegram_client=MagicMock(),
                    livekit_connect_fn=AsyncMock(),
                    livekit_connected=False,
                    listen_fn=mock_listen_fn,
                    mqtt_client=None,
                    on_stt_event=None,
                    actions_config=config,
                )
                mock_dispatch.assert_not_called()

        # Let's verify that with an exact match "chiama" -> 100% -> should match!
        mock_listen_fn_exact = AsyncMock(return_value="chiama")
        with patch("alexa_custom.actions.dispatch", new_callable=AsyncMock) as mock_dispatch_exact:
            with patch("alexa_custom.tts.get_engine"):
                await handle_ask(
                    action,
                    telegram_client=MagicMock(),
                    livekit_connect_fn=AsyncMock(),
                    livekit_connected=False,
                    listen_fn=mock_listen_fn_exact,
                    mqtt_client=None,
                    on_stt_event=None,
                    actions_config=config,
                )
                mock_dispatch_exact.assert_called_once()
