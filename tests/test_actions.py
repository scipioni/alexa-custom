import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from alexa_custom.actions import (
    ActionContext,
    ActionRegistry,
    _match_glob_pattern,
    _run_action,
    _trigger_matches_patterns,
    _trigger_phrases,
    dispatch,
    italian_phonetic,
    match_trigger,
    match_trigger_regex,
    normalize_text,
    registry,
    substitute_action_params,
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

    def test_esistente_assistente_alignment(self):
        assert italian_phonetic("esistente") == italian_phonetic("assistente")
        assert italian_phonetic("esistenti") == italian_phonetic("assistenti")
        assert italian_phonetic("esistenza") == italian_phonetic("assistenza")

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
    from alexa_custom.actions import ActionError

    reg = ActionRegistry()
    # Unknown action types raise ActionError so _run_action can notify the UI.
    with pytest.raises(ActionError, match="unknown action type"):
        await reg.execute("unknown")


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
            # An extra word alongside an exact word-level hit must still
            # match: free-vocabulary backends (sherpa-onnx) have no grammar
            # constraint on ask replies, so a short "sì"/"no" answer often
            # picks up a trailing captured word before the transcript is
            # matched. No fuzzy/prefix leniency though — only a whole-word
            # phonetic hit counts, "sissignore" (one word) still must not.
            assert match_trigger("si grazie", triggers, algorithm=algo) is not None
            assert match_trigger("sissignore", triggers, algorithm=algo) is None

    def test_trigger_phrases_uses_commands(self):
        from alexa_custom.actions import _trigger_phrases

        t = Trigger(commands=["si", "sì", "va bene", "ok"], phrase="si", actions=[])
        assert _trigger_phrases(t) == ["si", "sì", "va bene", "ok"]

    def test_trigger_phrases_falls_back_to_phrase_and_aliases(self):
        from alexa_custom.actions import _trigger_phrases

        t = Trigger(commands=[], phrase="si", actions=[], aliases=["va bene"])
        assert _trigger_phrases(t) == ["si", "va bene"]

    @pytest.mark.asyncio
    async def test_ask_grammar_includes_reply_aliases(self):
        from alexa_custom.actions import handle_ask

        # The Vosk grammar handed to listen_fn must contain every command/alias
        # the matcher accepts; otherwise the recognizer physically cannot emit
        # the alias on real hardware and the reply could never match.
        on_reply = [
            Trigger(
                commands=["si", "sì", "va bene", "certo"],
                phrase="si",
                actions=[],
                with_wake=True,
            ),
            Trigger(
                commands=["no", "annulla"], phrase="no", actions=[], with_wake=True
            ),
        ]
        action = ActionEntry(type="ask", params={"text": "vuoi?", "timeout": 1.0})
        action.on_reply = on_reply

        mock_listen_fn = AsyncMock(return_value="")  # empty → no reply matching
        _ctx = ActionContext(telegram_client=MagicMock(), listen_fn=mock_listen_fn)
        with patch("alexa_custom.tts.get_engine"):
            await handle_ask(
                action,
                ctx=_ctx,
                listen_fn=mock_listen_fn,
                mqtt_client=None,
                on_stt_event=None,
                actions_config=None,
            )

        mock_listen_fn.assert_called_once()
        passed = mock_listen_fn.call_args.kwargs.get("phrases") or []
        for expected in ("si", "va bene", "certo", "no", "annulla"):
            assert expected in passed, f"{expected!r} missing from grammar: {passed}"

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

    # 4.7 implicit gap cap — regression for conf/history.jsonl 2026-07-13
    # (a ~250-word ambient-broadcast transcript spuriously matched "chiam*
    # assistenza" via unbounded adjacent-token distance, dispatching a real
    # sos action). See _MAX_IMPLICIT_GAP_WORDS in actions.py.
    def test_sos_pattern_matches_real_command(self):
        assert _match_glob_pattern("chiam* assistenza", "chiama assistenza")

    def test_sos_pattern_tolerates_small_insertion(self):
        assert _match_glob_pattern("chiam* assistenza", "chiama pure assistenza")

    def test_sos_pattern_rejects_distant_words_in_long_transcript(self):
        # Reproduces the false positive verbatim: "chiamava" (matches "chiam*")
        # and "assistenza"-adjacent content far apart in an unrelated transcript.
        transcript = (
            "la piazzetta chiamava tanto a cui batterta da un approccio elega "
            "anche la storia rimane nelle nostre vite di giorno quindi e una "
            "questione che non poteva male a chiuso il ferro ci sono quindi "
            "dario edoardo igor a entrare subito in chiesa la prima morte "
            "roperta la quale ha dedicato una delle can della musica italiana "
            "e che oggi ricorda cosi il loro grande amore assistenza"
        )
        assert not _match_glob_pattern("chiam* assistenza", transcript)

    def test_explicit_wildcard_still_unbounded(self):
        # An author-opted-in '*' must keep its full-transcript reach —
        # only the implicit (no-'*') adjacency case is capped.
        far_apart = "accendi " + "per favore " * 10 + "le luci"
        assert _match_glob_pattern("accend* * luci", far_apart)

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


class TestCommandRegexConfig:
    def test_command_regex_absent_defaults_to_empty_list(self):
        from alexa_custom.config import _parse_triggers

        raw = [{"phrase": "chiama", "actions": [{"type": "log"}]}]
        triggers = _parse_triggers(raw, "test")
        assert triggers[0].command_regex == []

    def test_command_regex_parsed_as_list(self):
        from alexa_custom.config import _parse_triggers

        raw = [
            {
                "phrase": "caduta",
                "actions": [{"type": "log"}],
                "command_regex": ["caduta_(?P<stanza>.+)"],
            }
        ]
        triggers = _parse_triggers(raw, "test")
        assert triggers[0].command_regex == ["caduta_(?P<stanza>.+)"]

    def test_command_regex_single_string_coerced_to_list(self):
        from alexa_custom.config import _parse_triggers

        raw = [
            {
                "phrase": "caduta",
                "actions": [{"type": "log"}],
                "command_regex": "caduta_(?P<stanza>.+)",
            }
        ]
        triggers = _parse_triggers(raw, "test")
        assert triggers[0].command_regex == ["caduta_(?P<stanza>.+)"]

    def test_command_regex_non_list_non_string_raises_config_error(self):
        from alexa_custom.config import ConfigError, _parse_triggers

        raw = [
            {
                "phrase": "caduta",
                "actions": [{"type": "log"}],
                "command_regex": {"not": "valid"},
            }
        ]
        with pytest.raises(ConfigError, match="command_regex must be a string or list"):
            _parse_triggers(raw, "test")


class TestMatchTriggerRegex:
    def test_matches_and_captures_named_group(self):
        trigger = Trigger(
            phrase="caduta",
            actions=[],
            command_regex=["caduta_(?P<stanza>.+)"],
        )
        matched, groups = match_trigger_regex("caduta_bagno", [trigger])
        assert matched is trigger
        assert groups == {"stanza": "bagno"}

    def test_no_match_returns_none_and_empty_groups(self):
        trigger = Trigger(
            phrase="caduta",
            actions=[],
            command_regex=["caduta_(?P<stanza>.+)"],
        )
        matched, groups = match_trigger_regex("altro_evento", [trigger])
        assert matched is None
        assert groups == {}

    def test_fullmatch_rejects_partial_suffix(self):
        # A stray suffix must not falsely match — re.fullmatch, not re.match.
        trigger = Trigger(phrase="caduta", actions=[], command_regex=["caduta_bagno"])
        matched, _ = match_trigger_regex("caduta_bagno_extra", [trigger])
        assert matched is None

    def test_pattern_without_groups_returns_empty_dict(self):
        trigger = Trigger(phrase="caduta", actions=[], command_regex=["caduta_bagno"])
        matched, groups = match_trigger_regex("caduta_bagno", [trigger])
        assert matched is trigger
        assert groups == {}

    def test_first_matching_trigger_wins(self):
        first = Trigger(phrase="a", actions=[], command_regex=["caduta_(?P<x>.+)"])
        second = Trigger(phrase="b", actions=[], command_regex=["caduta_(?P<x>.+)"])
        matched, _ = match_trigger_regex("caduta_bagno", [first, second])
        assert matched is first

    def test_invalid_regex_is_skipped_not_raised(self):
        trigger = Trigger(phrase="bad", actions=[], command_regex=["caduta_(?P<x>"])
        matched, groups = match_trigger_regex("caduta_bagno", [trigger])
        assert matched is None
        assert groups == {}

    def test_empty_triggers_list(self):
        assert match_trigger_regex("anything", []) == (None, {})

    def test_command_regex_excluded_from_voice_matching_phrases(self):
        # _trigger_phrases() feeds both the fuzzy voice matcher and the Vosk
        # grammar (see its docstring) — command_regex must never appear there,
        # or a raw regex string could leak into spoken-command matching/grammar.
        trigger = Trigger(
            commands=["caduta bagno"],
            command_regex=["caduta_(?P<stanza>.+)"],
            actions=[],
        )
        assert _trigger_phrases(trigger) == ["caduta bagno"]


class TestSubstituteActionParams:
    def test_replaces_placeholder_in_top_level_string(self):
        actions = [
            ActionEntry(type="say", params={"text": "Caduta rilevata in <stanza>"})
        ]
        result = substitute_action_params(actions, {"stanza": "bagno"})
        assert result[0].params["text"] == "Caduta rilevata in bagno"

    def test_original_actions_left_untouched(self):
        actions = [ActionEntry(type="say", params={"text": "in <stanza>"})]
        substitute_action_params(actions, {"stanza": "bagno"})
        assert actions[0].params["text"] == "in <stanza>"

    def test_replaces_placeholder_in_nested_dict_and_list(self):
        actions = [
            ActionEntry(
                type="mqtt_publish",
                params={
                    "topic": "home/<stanza>/alarm",
                    "extra": {"nested": ["<stanza> triggered"]},
                },
            )
        ]
        result = substitute_action_params(actions, {"stanza": "bagno"})
        assert result[0].params["topic"] == "home/bagno/alarm"
        assert result[0].params["extra"]["nested"] == ["bagno triggered"]

    def test_no_placeholder_leaves_text_unchanged(self):
        actions = [ActionEntry(type="say", params={"text": "nessun placeholder"})]
        result = substitute_action_params(actions, {"stanza": "bagno"})
        assert result[0].params["text"] == "nessun placeholder"

    def test_multiple_groups_substituted(self):
        actions = [ActionEntry(type="say", params={"text": "<evento> in <stanza>"})]
        result = substitute_action_params(
            actions, {"evento": "caduta", "stanza": "bagno"}
        )
        assert result[0].params["text"] == "caduta in bagno"

    def test_substitutes_inside_ask_on_reply(self):
        # Mirrors conf/actions/user.yaml's "Sensore BAGNO" trigger: an `ask`
        # action whose on_reply actions also reference the captured group.
        actions = [
            ActionEntry(
                type="ask",
                params={"text": "Caduta rilevata in <stanza>. Confermi?"},
                on_reply=[
                    Trigger(
                        commands=["si"],
                        actions=[
                            ActionEntry(
                                type="telegram",
                                params={"text": "Caduta in <stanza> — collegati"},
                            )
                        ],
                    )
                ],
            )
        ]
        result = substitute_action_params(actions, {"stanza": "bagno"})
        assert result[0].params["text"] == "Caduta rilevata in bagno. Confermi?"
        assert (
            result[0].on_reply[0].actions[0].params["text"]
            == "Caduta in bagno — collegati"
        )

    def test_substitutes_inside_on_else_and_nested_ask(self):
        # on_else can itself hold another `ask` with its own on_reply/on_else —
        # substitution must recurse through every level, not just one.
        actions = [
            ActionEntry(
                type="ask",
                params={"text": "in <stanza>?"},
                on_else=[
                    ActionEntry(
                        type="ask",
                        params={"text": "ripeto: in <stanza>?"},
                        on_reply=[
                            Trigger(
                                commands=["si"],
                                actions=[
                                    ActionEntry(
                                        type="say",
                                        params={"text": "ok, <stanza>"},
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
        result = substitute_action_params(actions, {"stanza": "bagno"})
        nested_ask = result[0].on_else[0]
        assert nested_ask.params["text"] == "ripeto: in bagno?"
        assert nested_ask.on_reply[0].actions[0].params["text"] == "ok, bagno"

    def test_on_reply_on_else_left_untouched_on_original(self):
        original = ActionEntry(
            type="ask",
            params={"text": "in <stanza>"},
            on_reply=[
                Trigger(
                    commands=["si"],
                    actions=[ActionEntry(type="say", params={"text": "<stanza>"})],
                )
            ],
        )
        substitute_action_params([original], {"stanza": "bagno"})
        assert original.params["text"] == "in <stanza>"
        assert original.on_reply[0].actions[0].params["text"] == "<stanza>"


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
        # 2026-06-14 is a Sunday — the message includes the weekday and date.
        assert "Milano tomorrow, Sunday, June 14, the weather will be" in spoken_text

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_rain_reports_next_rain(
        self, mock_client_class, mock_get_engine
    ):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "current": {"time": "2026-06-13T10:00"},
            "hourly": {
                "time": [
                    "2026-06-13T08:00",  # before "now" → ignored
                    "2026-06-13T15:00",  # rain, 70% → the answer
                    "2026-06-13T16:00",
                ],
                "weather_code": [0, 80, 80],
                "precipitation": [0.0, 1.2, 0.8],
                "precipitation_probability": [0, 70, 60],
            },
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(
            type="meteo_rain", params={"city": "Verona", "lang": "it-IT"}
        )

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="quando pioverà",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "Verona" in spoken_text
        assert "pioverà oggi" in spoken_text  # same day as current.time
        assert "verso le 15" in spoken_text
        assert "70 per cento" in spoken_text

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_rain_no_rain(self, mock_client_class, mock_get_engine):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "current": {"time": "2026-06-13T10:00"},
            "hourly": {
                "time": ["2026-06-13T11:00", "2026-06-13T12:00"],
                "weather_code": [0, 1],
                "precipitation": [0.0, 0.0],
                "precipitation_probability": [0, 5],
            },
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(
            type="meteo_rain", params={"city": "Verona", "lang": "it-IT"}
        )

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="quando pioverà",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "non è prevista pioggia" in spoken_text

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_rain_skips_past_and_trace(
        self, mock_client_class, mock_get_engine
    ):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "current": {"time": "2026-06-13T12:00"},
            "hourly": {
                "time": [
                    "2026-06-13T02:00",  # rain but already past → skip
                    "2026-06-13T13:00",  # 10% trace amount → skip
                    "2026-06-13T18:00",  # 55% real rain → the answer
                ],
                "weather_code": [80, 80, 61],
                "precipitation": [2.0, 0.1, 0.6],
                "precipitation_probability": [90, 10, 55],
            },
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(
            type="meteo_rain", params={"city": "Verona", "lang": "it-IT"}
        )

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="quando pioverà",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "verso le 18" in spoken_text
        assert "55 per cento" in spoken_text

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_sun_already_sunny(self, mock_client_class, mock_get_engine):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "current": {"time": "2026-06-13T10:00", "weather_code": 0},
            "hourly": {
                "time": ["2026-06-13T10:00", "2026-06-13T11:00"],
                "weather_code": [0, 0],
            },
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(
            type="meteo_sun", params={"city": "Verona", "lang": "it-IT"}
        )

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="quando ci sarà il sole",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "c'è già il sole" in spoken_text

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_sun_next_clear_daytime_hour(
        self, mock_client_class, mock_get_engine
    ):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Cloudy at night now; a clear hour before dawn is skipped (night),
        # the first daylight clear hour tomorrow is the answer.
        mock_resp.json.return_value = {
            "current": {"time": "2026-06-13T22:00", "weather_code": 3},
            "hourly": {
                "time": [
                    "2026-06-13T23:00",  # overcast
                    "2026-06-14T06:00",  # clear but before daylight window → skip
                    "2026-06-14T10:00",  # clear, daytime → the answer
                ],
                "weather_code": [3, 0, 0],
            },
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(
            type="meteo_sun", params={"city": "Verona", "lang": "it-IT"}
        )

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="quando ci sarà il sole",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "ci sarà il sole domani" in spoken_text
        assert "verso le 10" in spoken_text

    @pytest.mark.asyncio
    @patch("alexa_custom.tts.get_engine")
    @patch("httpx.AsyncClient")
    async def test_meteo_sun_no_sun(self, mock_client_class, mock_get_engine):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        mock_client = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "current": {"time": "2026-06-13T10:00", "weather_code": 3},
            "hourly": {
                "time": ["2026-06-13T11:00", "2026-06-13T12:00"],
                "weather_code": [3, 3],
            },
        }
        mock_client.get.return_value = mock_resp

        action = ActionEntry(
            type="meteo_sun", params={"city": "Verona", "lang": "it-IT"}
        )

        await _run_action(
            action,
            ActionContext(telegram_client=MagicMock()),
            transcript="quando ci sarà il sole",
        )

        mock_engine.say.assert_called_once()
        spoken_text = mock_engine.say.call_args[0][0]
        assert "non è previsto sole" in spoken_text


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
@patch("alexa_custom.tts.get_engine")
@patch("alexa_custom.stt_gating.resolve_capture_source")
@patch("alexa_custom.audio_ops.record_wav_file")
@patch("alexa_custom.audio_ops.play_wav_file")
@patch("alexa_custom.audio_ops.play_tone")
async def test_record_and_playback_action(
    mock_play_tone,
    mock_play_wav,
    mock_record_wav,
    mock_resolve_capture_source,
    mock_get_engine,
):
    mock_engine = MagicMock()
    mock_get_engine.return_value = mock_engine

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

    # Verify that play_wav_file was called with the raw recorded wav
    mock_play_wav.assert_called_once()
    assert mock_play_wav.call_args[0][0] == args[0]

    # Verify that say was called to announce the calculated RMS score (fallback/empty file -> score 1)
    mock_engine.say.assert_called_once()
    assert "1 su dieci" in mock_engine.say.call_args[0][0]


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


# ── action error notification ────────────────────────────────────────────────


class TestActionErrorNotification:
    """A problematic action must notify the UI via an ``action_error`` event
    without aborting the trigger's remaining actions."""

    def _ctx_with_recorder(self, **kwargs):
        events: list[tuple[str, dict]] = []
        ctx = ActionContext(
            telegram_client=MagicMock(),
            on_stt_event=lambda e, d: events.append((e, d)),
            **kwargs,
        )
        return ctx, events

    @pytest.mark.asyncio
    async def test_mqtt_publish_no_client_notifies_ui(self):
        ctx, events = self._ctx_with_recorder(mqtt_client=None)
        action = ActionEntry(type="mqtt_publish", params={"topic": "x", "payload": "y"})

        await _run_action(action, ctx)

        errors = [d for e, d in events if e == "action_error"]
        assert len(errors) == 1
        assert errors[0]["action"] == "mqtt_publish"
        assert "no mqtt_client available" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_mqtt_publish_no_topic_notifies_ui(self):
        ctx, events = self._ctx_with_recorder(mqtt_client=AsyncMock())
        action = ActionEntry(type="mqtt_publish", params={"payload": "y"})

        await _run_action(action, ctx)

        errors = [d for e, d in events if e == "action_error"]
        assert len(errors) == 1
        assert "no topic provided" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_unknown_action_type_notifies_ui(self):
        ctx, events = self._ctx_with_recorder()
        action = ActionEntry(type="does_not_exist", params={})

        await _run_action(action, ctx)

        errors = [d for e, d in events if e == "action_error"]
        assert len(errors) == 1
        assert "does_not_exist" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_unexpected_exception_notifies_ui(self):
        ctx, events = self._ctx_with_recorder()

        @registry.register("_boom_test")
        async def _boom(**_):
            raise RuntimeError("kaboom")

        try:
            await _run_action(ActionEntry(type="_boom_test", params={}), ctx)
        finally:
            registry._handlers.pop("_boom_test", None)

        errors = [d for e, d in events if e == "action_error"]
        assert len(errors) == 1
        assert "kaboom" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_successful_action_does_not_notify(self):
        ctx, events = self._ctx_with_recorder()
        action = ActionEntry(type="log", params={"message": "hi"})

        await _run_action(action, ctx)

        assert not [e for e, _ in events if e == "action_error"]

    @pytest.mark.asyncio
    async def test_failing_action_does_not_abort_remaining_actions(self):
        ctx, events = self._ctx_with_recorder(mqtt_client=None)
        ran: list[str] = []

        @registry.register("_marker_test")
        async def _marker(action, **_):
            ran.append(action.params.get("id", ""))

        trigger = Trigger(
            commands=["x"],
            phrase="x",
            actions=[
                ActionEntry(type="mqtt_publish", params={"topic": "t"}),
                ActionEntry(type="_marker_test", params={"id": "second"}),
            ],
        )
        try:
            await dispatch(trigger, ctx)
        finally:
            registry._handlers.pop("_marker_test", None)

        # The mqtt failure was reported, and the action after it still ran.
        assert [d for e, d in events if e == "action_error"]
        assert ran == ["second"]

    def test_action_error_event_emits_toast(self):
        """web.py must turn an action_error event into an error toast."""
        from alexa_custom.web import WebServer

        srv = WebServer()
        sent: list[tuple[str, dict]] = []
        srv._enqueue = lambda event_type, data: sent.append((event_type, data))

        srv.on_stt_event("action_error", {"action": "mqtt_publish", "message": "boom"})

        assert ("toast", {"message": "boom", "level": "error"}) in sent


# ── match_short_reply_fallback() ─────────────────────────────────────────────


class TestShortReplyFallback:
    """The closed-set rescue for short 'sì'/'no' answers a free-vocabulary
    backend (sherpa-onnx) mis-transcribes and the strict matcher scores 0."""

    def _yes_no(self):
        yes = Trigger(
            commands=["si", "sì", "va bene", "certo", "ok", "dai"],
            phrase="si",
            actions=[],
        )
        no = Trigger(commands=["no", "no no", "annulla"], phrase="no", actions=[])
        return [yes, no]

    def test_exact_yes(self):
        from alexa_custom.actions import match_short_reply_fallback

        trig, score = match_short_reply_fallback("si", self._yes_no())
        assert trig is not None and trig.phrase == "si"
        assert score == 100.0

    def test_exact_no(self):
        from alexa_custom.actions import match_short_reply_fallback

        trig, _ = match_short_reply_fallback("no", self._yes_no())
        assert trig is not None and trig.phrase == "no"

    @pytest.mark.parametrize("heard", ["se", "sei"])
    def test_near_miss_yes(self, heard):
        # sherpa's typical mis-transcriptions of "sì" resolve to the yes group.
        from alexa_custom.actions import match_short_reply_fallback

        trig, _ = match_short_reply_fallback(heard, self._yes_no())
        assert trig is not None and trig.phrase == "si", f"{heard!r} should be yes"

    def test_near_miss_no(self):
        from alexa_custom.actions import match_short_reply_fallback

        trig, _ = match_short_reply_fallback("non", self._yes_no())
        assert trig is not None and trig.phrase == "no"

    def test_short_word_with_trailing_filler(self):
        # Free-vocab capture often appends a stray word before the endpoint fires.
        from alexa_custom.actions import match_short_reply_fallback

        trig, _ = match_short_reply_fallback("sì grazie", self._yes_no())
        assert trig is not None and trig.phrase == "si"

    def test_ambiguous_falls_through(self):
        # "so" is equidistant from "sì" and "no" — do not guess; let on_else run.
        from alexa_custom.actions import match_short_reply_fallback

        trig, _ = match_short_reply_fallback("so", self._yes_no())
        assert trig is None

    def test_unrelated_word_rejected(self):
        from alexa_custom.actions import match_short_reply_fallback

        trig, _ = match_short_reply_fallback("accendi la luce", self._yes_no())
        assert trig is None

    def test_long_only_reply_not_loosened(self):
        # A group with no short phrase is left to the strict matcher/threshold —
        # the fallback must never rescue multi-word replies.
        from alexa_custom.actions import match_short_reply_fallback

        triggers = [Trigger(commands=["chiama"], phrase="chiama", actions=[])]
        trig, _ = match_short_reply_fallback("chiamare", triggers)
        assert trig is None
