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


# ── set_volume action handler ────────────────────────────────────────────────────


class TestSetVolume:
    @pytest.mark.asyncio
    async def test_volume_up(self):
        action = ActionEntry(type="set_volume", params={"mode": "up", "step": 0.1})
        with (
            patch("alexa_custom.audio_hw.get_output_volume", return_value=0.5),
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_state"),
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
            patch("alexa_custom.audio_hw.save_volume_state"),
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
            patch("alexa_custom.audio_hw.save_volume_state"),
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
            patch("alexa_custom.audio_hw.save_volume_state"),
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
            patch("alexa_custom.audio_hw.save_volume_state"),
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
            patch("alexa_custom.audio_hw.save_volume_state"),
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
            patch("alexa_custom.audio_hw.save_volume_state"),
            patch("pulsectl.Pulse"),
            patch("alexa_custom.audio.play_tone") as mock_tone,
        ):
            from alexa_custom.actions import registry

            await registry.execute("set_volume", action=action)
            mock_set.assert_not_called()
            mock_tone.assert_not_called()


# ── save/load volume state ────────────────────────────────────────────────────────


class TestVolumeState:
    def test_save_and_load_roundtrip(self, tmp_path):
        from alexa_custom import audio_hw

        state_file = tmp_path / "state.yaml"
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            audio_hw.save_volume_state(0.7)
            assert state_file.read_text().strip() == "output_volume: 0.7"

            audio_hw._OUTPUT_VOLUME = 0.0
            loaded = audio_hw.load_volume_state()
            assert loaded is not None
            assert abs(loaded - 0.7) < 0.001
            assert abs(audio_hw._OUTPUT_VOLUME - 0.7) < 0.001

    def test_missing_file_returns_none(self):
        from alexa_custom import audio_hw

        with patch.object(audio_hw, "_STATE_FILE", "/nonexistent/state.yaml"):
            assert audio_hw.load_volume_state() is None

    def test_malformed_file_returns_none(self, tmp_path):
        from alexa_custom import audio_hw

        state_file = tmp_path / "state.yaml"
        state_file.write_text("not: valid: yaml: [")
        with patch.object(audio_hw, "_STATE_FILE", str(state_file)):
            assert audio_hw.load_volume_state() is None


# ── set_volume_from_transcript action handler ───────────────────────────────────


class TestSetVolumeFromTranscript:
    @pytest.mark.asyncio
    async def test_sets_volume_from_digit_percentage(self):
        action = ActionEntry(type="set_volume_from_transcript")
        with (
            patch("alexa_custom.audio_hw.set_output_volume") as mock_set,
            patch("alexa_custom.audio_hw.save_volume_state") as mock_save,
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
            patch("alexa_custom.audio_hw.save_volume_state"),
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
            patch("alexa_custom.audio_hw.save_volume_state"),
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
