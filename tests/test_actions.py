import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from alexa_custom.actions import (
    ActionContext,
    ActionRegistry,
    _match_glob_pattern,
    _run_action,
    _trigger_matches_patterns,
    italian_phonetic,
    match_trigger,
    normalize_text,
)
from alexa_custom.config import ActionEntry, Trigger


# ── normalize_text() ────────────────────────────────────────────────────────


class TestNormalizeText:
    def test_strip_punctuation(self):
        assert normalize_text("che tempo farà domani?") == "che tempo fara domani"
        assert normalize_text("ciao! come va...") == "ciao come va"
        assert normalize_text("test (con parentesi)") == "test con parentesi"

    def test_lowercase_and_diacritics(self):
        assert normalize_text("Sì, Còmé nò") == "si come no"


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


class TestContentWordFloor:
    """The fuzzy fallback requires ≥1 phonetic content-word overlap, so a
    transcript that only shares stopwords with a trigger no longer fires it."""

    def test_stopword_only_overlap_rejected(self):
        # Shares "la" with the trigger but no content word (accendi/luce).
        triggers = [_trigger("accendi la luce")]
        assert match_trigger("chiudi la finestra", triggers) is None

    def test_content_word_present_matches(self):
        triggers = [_trigger("accendi la luce")]
        assert match_trigger("accendi la luce adesso", triggers) is not None

    def test_content_word_phonetic_variant_matches(self):
        # "accendere"/"luce" are phonetic/inflected variants of the content
        # words; the floor is satisfied via prefix-anchored phonetic matching.
        triggers = [_trigger("accendi la luce")]
        assert match_trigger("puoi accendere la luce", triggers) is not None

    def test_short_only_phrase_skips_floor(self):
        # "si" has no content word (phonetic length < 3) → floor skipped, falls
        # through to the short-phrase exact-match guard.
        triggers = [_trigger("si")]
        assert match_trigger("si", triggers) is not None
        assert match_trigger("no", triggers) is None


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
        ctx = ActionContext(
            telegram_client=MagicMock(),
            livekit_connect_fn=AsyncMock(),
            livekit_connected=False,
        )
        await _run_action(mock_action, ctx)

        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        assert args[0] == "log"
        assert kwargs["action"] == mock_action


# ── configurable matching tests ──────────────────────────────────────────────


class TestConfigurableMatching:
    def test_levenshtein_distance(self):
        from rapidfuzz.distance import Levenshtein as _lev

        assert _lev.distance("si", "si") == 0
        assert _lev.distance("si", "se") == 1
        assert _lev.distance("si", "si grazie") == 7
        assert _lev.distance("ciao", "miao") == 1
        assert _lev.distance("", "abc") == 3

    def test_get_similarity_score_all_algorithms(self):
        from alexa_custom.actions import get_similarity_score

        # 1. levenshtein similarity
        assert (
            get_similarity_score("ciao", "miao", "levenshtein") == 75.0
        )  # (1 - 1/4) * 100
        assert get_similarity_score("si", "si", "levenshtein") == 100.0

        # 2. ratio similarity
        assert get_similarity_score("si", "si", "ratio") == 100.0

        # 3. token_set_ratio similarity
        assert get_similarity_score("si", "si", "token_set_ratio") == 100.0

    def test_match_trigger_with_custom_algorithms_and_thresholds(self):
        triggers = [_trigger("accendi la luce")]

        # token_set_ratio is tolerant to word ordering & extra words
        assert (
            match_trigger(
                "luce accendi la", triggers, threshold=80, algorithm="token_set_ratio"
            )
            is not None
        )

        # levenshtein is strict about character alignment and sequence
        assert (
            match_trigger(
                "luce accendi la", triggers, threshold=80, algorithm="levenshtein"
            )
            is None
        )

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

        _ctx = ActionContext(
            telegram_client=MagicMock(),
            livekit_connect_fn=AsyncMock(),
            listen_fn=mock_listen_fn,
            actions_config=config,
        )
        with patch(
            "alexa_custom.actions.dispatch", new_callable=AsyncMock
        ) as mock_dispatch:
            with patch("alexa_custom.tts.get_engine"):
                await handle_ask(
                    action,
                    ctx=_ctx,
                    listen_fn=mock_listen_fn,
                    mqtt_client=None,
                    on_stt_event=None,
                    actions_config=config,
                )
                mock_dispatch.assert_not_called()

        # Let's verify that with an exact match "chiama" -> 100% -> should match!
        mock_listen_fn_exact = AsyncMock(return_value="chiama")
        _ctx_exact = ActionContext(
            telegram_client=MagicMock(),
            livekit_connect_fn=AsyncMock(),
            listen_fn=mock_listen_fn_exact,
            actions_config=config,
        )
        with patch(
            "alexa_custom.actions.dispatch", new_callable=AsyncMock
        ) as mock_dispatch_exact:
            with patch("alexa_custom.tts.get_engine"):
                await handle_ask(
                    action,
                    ctx=_ctx_exact,
                    listen_fn=mock_listen_fn_exact,
                    mqtt_client=None,
                    on_stt_event=None,
                    actions_config=config,
                )
                mock_dispatch_exact.assert_called_once()


# ── set_volume action handler ────────────────────────────────────────────────────


class TestSetVolume:
    @pytest.mark.asyncio
    async def test_volume_up(self):
        action = ActionEntry(type="set_volume", params={"mode": "up", "step": 0.1})
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=0.5),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 0.6) < 0.001
            mock_tone.assert_called_once_with("info")

    @pytest.mark.asyncio
    async def test_volume_down(self):
        action = ActionEntry(type="set_volume", params={"mode": "down", "step": 0.1})
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=0.5),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 0.4) < 0.001
            mock_tone.assert_called_once_with("info")

    @pytest.mark.asyncio
    async def test_absolute_set(self):
        action = ActionEntry(
            type="set_volume", params={"mode": "absolute", "value": 0.3}
        )
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=0.5),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone"),
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 0.3) < 0.001

    @pytest.mark.asyncio
    async def test_clamp_max(self):
        action = ActionEntry(type="set_volume", params={"mode": "up", "step": 0.6})
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=0.5),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone"),
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_clamp_min(self):
        action = ActionEntry(type="set_volume", params={"mode": "down", "step": 0.6})
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=0.5),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone"),
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 0.0) < 0.001

    @pytest.mark.asyncio
    async def test_noop_at_max_skips_tone(self):
        action = ActionEntry(type="set_volume", params={"mode": "up", "step": 0.1})
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=1.0),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_not_called()
            mock_tone.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_at_min_skips_tone(self):
        action = ActionEntry(type="set_volume", params={"mode": "down", "step": 0.1})
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=0.0),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_not_called()
            mock_tone.assert_not_called()


class TestSetVolumeFromTranscript:
    @pytest.mark.asyncio
    async def test_sets_volume_from_digit_percentage(self):
        action = ActionEntry(type="set_volume_from_transcript")
        with (
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config") as mock_save,
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute(
                "set_volume_from_transcript",
                action=action,
                transcript="volume al 80%",
            )
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 0.80) < 0.001
            mock_save.assert_called_once_with(0.80)
            mock_tone.assert_called_once_with("info")

    @pytest.mark.asyncio
    async def test_sets_volume_from_italian_word(self):
        action = ActionEntry(type="set_volume_from_transcript")
        with (
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone"),
        ):
            from alexa_custom.actions import registry

            await registry.execute(
                "set_volume_from_transcript",
                action=action,
                transcript="imposta volume a settanta",
            )
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 0.70) < 0.001

    @pytest.mark.asyncio
    async def test_noop_on_no_number(self):
        action = ActionEntry(type="set_volume_from_transcript")
        with (
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute(
                "set_volume_from_transcript",
                action=action,
                transcript="alza il volume",
            )
            mock_set.assert_not_called()
            mock_tone.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_on_none_transcript(self):
        action = ActionEntry(type="set_volume_from_transcript")
        with (
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute(
                "set_volume_from_transcript",
                action=action,
                transcript=None,
            )
            mock_set.assert_not_called()
            mock_tone.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_volume(self):
        action = ActionEntry(type="set_volume_from_transcript")
        with (
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_config"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone"),
        ):
            from alexa_custom.actions import registry

            await registry.execute(
                "set_volume_from_transcript",
                action=action,
                transcript="volume al 0%",
            )
            mock_set.assert_called_once()
            call_vol = mock_set.call_args[0][2]
            assert abs(call_vol - 0.0) < 0.001


# ── word-glob pattern matching ───────────────────────────────────────────────


def _pattern_trigger(phrase: str, patterns: list[str]) -> Trigger:
    return Trigger(phrase=phrase, actions=[], patterns=patterns)


class TestGlobPatternMatching:
    # 4.1 prefix wildcard + word gap
    def test_prefix_wildcard_with_gap(self):
        assert _match_glob_pattern("accend* * luci", "accendi le luci del salotto")

    def test_prefix_wildcard_direct(self):
        assert _match_glob_pattern("accend* * luci", "accendimi le luci")

    # 4.2 standalone * matches single word and zero words
    def test_gap_matches_single_word(self):
        assert _match_glob_pattern("accend* * luci", "accendi le luci")

    def test_gap_matches_zero_words(self):
        assert _match_glob_pattern("accend* * luci", "accendi luci")

    def test_gap_matches_many_words(self):
        assert _match_glob_pattern("accend* * luci", "accenda per favore tutte le luci")

    # 4.3 phonetic tolerance on literal token
    def test_phonetic_tolerance_luce_matches_luci(self):
        assert _match_glob_pattern("accend* * luci", "accendi le luce")

    # 4.4 order enforcement
    def test_wrong_order_does_not_match(self):
        assert not _match_glob_pattern("accend* * luci", "luci accendi")

    def test_wrong_order_reversed(self):
        assert not _match_glob_pattern("spegn* * luci", "luci spegni per favore")

    # extra: pattern with no wildcards
    def test_literal_pattern_exact(self):
        assert _match_glob_pattern("chiama", "chiama")

    def test_literal_pattern_no_match(self):
        assert not _match_glob_pattern("chiama", "spegni le luci")

    # 4.5 precedence: pattern hit wins over higher-scoring fuzzy trigger
    def test_pattern_takes_precedence_over_fuzzy(self):
        trigger_a = _trigger("accendi le luci")
        trigger_b = _pattern_trigger("spegni tutto", ["accend* * luci"])
        result = match_trigger("accendi le luci del salotto", [trigger_a, trigger_b])
        assert result is trigger_b

    # 4.6 backward compatibility: no patterns → fuzzy as today
    def test_no_patterns_fuzzy_still_works(self):
        triggers = [_trigger("chiama"), _trigger("saluta")]
        result = match_trigger("chiama", triggers)
        assert result is not None
        assert result.phrase == "chiama"

    def test_no_patterns_below_threshold_returns_none(self):
        triggers = [_trigger("chiama")]
        assert match_trigger("xyz", triggers) is None

    # _trigger_matches_patterns wrapper
    def test_trigger_matches_patterns_true(self):
        t = _pattern_trigger("luci", ["accend* * luci"])
        assert _trigger_matches_patterns(t, "accendi le luci")

    def test_trigger_matches_patterns_false(self):
        t = _pattern_trigger("luci", ["accend* * luci"])
        assert not _trigger_matches_patterns(t, "luci accendi")

    def test_trigger_no_patterns_false(self):
        t = _trigger("chiama")
        assert not _trigger_matches_patterns(t, "chiama")


class TestGlobPatternConfig:
    # 4.7 config parsing
    def test_patterns_absent_defaults_to_empty_list(self):
        from alexa_custom.config import _parse_triggers

        raw = [{"phrase": "chiama", "actions": [{"type": "log"}]}]
        triggers = _parse_triggers(raw, "test")
        assert triggers[0].patterns == []

    def test_patterns_parsed_correctly(self):
        from alexa_custom.config import _parse_triggers

        raw = [
            {
                "phrase": "luci",
                "actions": [{"type": "log"}],
                "patterns": ["accend* * luci", "spegn* * luci"],
            }
        ]
        triggers = _parse_triggers(raw, "test")
        assert triggers[0].patterns == ["accend* * luci", "spegn* * luci"]

    def test_patterns_non_list_raises_config_error(self):
        from alexa_custom.config import ConfigError, _parse_triggers

        raw = [{"phrase": "luci", "actions": [{"type": "log"}], "patterns": "accend*"}]
        with pytest.raises(ConfigError, match="patterns must be a list"):
            _parse_triggers(raw, "test")


class TestMeteoAction:
    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_action_success_italian_tomorrow(
        self, mock_client_class, mock_get_engine
    ):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        # Mock httpx client response
        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "daily": {
                "time": ["2026-06-13", "2026-06-14"],
                "weather_code": [0, 3],
                "temperature_2m_max": [25.4, 21.2],
                "temperature_2m_min": [14.3, 12.1],
            }
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(
            type="meteo", params={"city": "Milano", "days": "domani", "lang": "it-IT"}
        )

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="che tempo fa a Milano domani?",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "Milano" in spoken_text
        assert "coperto" in spoken_text.lower()
        assert "12" in spoken_text  # min temp rounded (12.1 -> 12)
        assert "21" in spoken_text  # max temp rounded (21.2 -> 21)

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_action_success_italian_today(
        self, mock_client_class, mock_get_engine
    ):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "daily": {
                "time": ["2026-06-13", "2026-06-14"],
                "weather_code": [0, 3],
                "temperature_2m_max": [25.4, 21.2],
                "temperature_2m_min": [14.3, 12.1],
            }
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(type="meteo", params={"lang": "it-IT"})

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="che tempo fa a torino oggi?",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "Torino" in spoken_text
        assert "cielo sereno" in spoken_text
        assert "14" in spoken_text  # min temp rounded (14.3 -> 14)
        assert "25" in spoken_text  # max temp rounded (25.4 -> 25)

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_action_success_english(
        self, mock_client_class, mock_get_engine
    ):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "daily": {
                "time": ["2026-06-13", "2026-06-14"],
                "weather_code": [61, 3],
                "temperature_2m_max": [18.1, 21.2],
                "temperature_2m_min": [9.9, 12.1],
            }
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(type="meteo", params={"lang": "en-US", "city": "Florence"})

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="what is the weather today?",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "Florence" in spoken_text
        assert "slight rain" in spoken_text.lower()
        assert "10" in spoken_text  # min temp rounded (9.9 -> 10)
        assert "18" in spoken_text  # max temp rounded (18.1 -> 18)

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_action_api_failure(self, mock_client_class, mock_get_engine):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Connection timed out")

        action = ActionEntry(type="meteo", params={"lang": "it-IT"})

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="meteo roma",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "Spiacente, impossibile recuperare le informazioni meteo" in spoken_text

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_action_language_fallback_from_config(
        self, mock_client_class, mock_get_engine
    ):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "daily": {
                "time": ["2026-06-13", "2026-06-14"],
                "weather_code": [0, 3],
                "temperature_2m_max": [25.4, 21.2],
                "temperature_2m_min": [14.3, 12.1],
            }
        }
        mock_client.get.return_value = mock_resp

        # No lang param in action entry
        action = ActionEntry(type="meteo", params={"city": "Milano"})

        # Setup mock actions_config
        mock_wake_word_group = MagicMock()
        mock_wake_word_group.word = "alexa"
        mock_wake_word_group.lang = "en-US"
        mock_config = MagicMock()
        mock_config.wake_words = [mock_wake_word_group]

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock(), actions_config=mock_config),
            transcript="weather forecast for Milano",
            wake_word="alexa",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        # Since it successfully resolved en-US from wake-word group config, it should speak in English!
        assert "Milano tomorrow the weather will be" in spoken_text


@pytest.mark.asyncio
async def test_restart_action():
    action = ActionEntry(type="restart", params={})
    with patch("os.execv") as mock_execv, patch("asyncio.sleep") as mock_sleep:
        await _run_action(action, ActionContext(telegram_client=MagicMock()))
        mock_sleep.assert_called_once_with(0.5)
        mock_execv.assert_called_once()
        args = mock_execv.call_args[0]
        assert len(args) == 2
        assert "python" in args[0]


@pytest.mark.asyncio
@patch("alexa_custom.stt_gating.resolve_capture_source")
@patch("alexa_custom.audio_ops.record_wav_file")
@patch("alexa_custom.audio_ops.play_wav_file")
@patch("alexa_custom.audio_ops.play_tone")
async def test_record_and_playback_action(
    mock_play_tone,
    mock_play_wav,
    mock_record_wav,
    mock_resolve_capture_source,
):
    mock_resolve_capture_source.return_value = ("mock_source", 2)

    action = ActionEntry(type="record_and_playback", params={"duration": 7.5})

    mock_config = MagicMock()
    mock_config.audio.input_device = "my_custom_mic"

    ctx = ActionContext(
        telegram_client=MagicMock(),
        actions_config=mock_config,
    )

    await _run_action(action, ctx)

    # Verify that resolve_capture_source was called with the correct device
    mock_resolve_capture_source.assert_called_once_with("my_custom_mic")

    # Verify that play_tone was called to announce recording
    mock_play_tone.assert_called_once_with("info")

    # Verify that record_wav_file was called with the correct source, channels, and duration
    mock_record_wav.assert_called_once()
    args, kwargs = mock_record_wav.call_args
    # First arg is file_path, second is duration
    assert args[1] == 7.5
    assert args[2] == "mock_source"
    assert args[3] == 2

    # Verify that play_wav_file was called
    mock_play_wav.assert_called_once()
    assert mock_play_wav.call_args[0][0] == args[0]


@pytest.mark.asyncio
@patch("alexa_custom.stt_gating.resolve_capture_source")
@patch("alexa_custom.audio_ops.record_wav_file")
@patch("alexa_custom.audio_ops.play_wav_file")
@patch("alexa_custom.audio_ops.play_tone")
async def test_register_and_playback_action(
    mock_play_tone,
    mock_play_wav,
    mock_record_wav,
    mock_resolve_capture_source,
):
    mock_resolve_capture_source.return_value = ("mock_source", 2)

    action = ActionEntry(type="register_and_playback", params={})

    mock_config = MagicMock()
    mock_config.audio.input_device = "my_custom_mic"

    ctx = ActionContext(
        telegram_client=MagicMock(),
        actions_config=mock_config,
    )

    await _run_action(action, ctx)

    # Defaults to 7.0 seconds
    args, kwargs = mock_record_wav.call_args
    assert args[1] == 7.0
