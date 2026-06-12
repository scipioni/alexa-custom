from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

<<<<<<< HEAD
import numpy as np
=======
>>>>>>> e70cbf7 (feat: autogain auto-mode (alexa-mic-test) + voice-activated autogain action)

<<<<<<< HEAD
from alexa_custom.autogain import (
<<<<<<< HEAD
    _compute_channel_balance,
    _compute_frequency_weighted_snr,
=======
    TEST_GAINS,
    _AUTO_PLAY_VOLUMES,
    _analyze_channel,
    _check_channel_balance,
>>>>>>> db0c56e (fix: multi-volume playback with far-distance weighting in acoustic calibration)
    _generate_pink_noise,
    _select_best_gain,
    main,
)
=======
from alexa_custom.autogain import TEST_GAINS, main
>>>>>>> 73b63b7 (refactor: autogain redesign - test all gains at all distances)


def _mock_config():
    cfg = MagicMock()
    cfg.tts.backend = "piper"
    cfg.tts.voice = "it-paola"
    cfg.tts.preroll_ms = 400
    cfg.audio.input_device = "default_mic"
    cfg.recognition.wake_tone = "wake"
    cfg.stt.stage1 = MagicMock()
    cfg.wake_words = []
    return cfg


@patch("alexa_custom.autogain._save_gain_to_config")
@patch("alexa_custom.autogain.load_secrets")
@patch("alexa_custom.autogain.load_config")
@patch("alexa_custom.autogain.init_engine")
@patch("alexa_custom.autogain.get_engine")
@patch("alexa_custom.autogain.get_stt_backend")
@patch("alexa_custom.autogain._capture_and_transcribe")
@patch("alexa_custom.autogain.set_input_gain")
@patch("alexa_custom.autogain.time.sleep")
def test_calibration_writes_config(
    mock_sleep,
    mock_set_gain,
    mock_capture,
    mock_get_stt,
    mock_get_engine,
    mock_init_engine,
    mock_load_config,
    mock_load_secrets,
    mock_save,
    capsys,
):
    mock_load_config.return_value = _mock_config()
    mock_tts = MagicMock()
    mock_get_engine.return_value = mock_tts
    mock_capture.return_value = ("ascolta assistente chiama aiuto", b"\x00\x00" * 8000)

    with patch.object(sys, "argv", ["alexa-autogain"]):
        main()

    captured = capsys.readouterr()
    assert "Microfono calibrato" in captured.out
    assert "MIGLIORE" in captured.out
    assert "scritto in config.yaml" in captured.out
    mock_save.assert_called_once()


@patch("alexa_custom.autogain._save_gain_to_config")
@patch("alexa_custom.autogain.load_secrets")
@patch("alexa_custom.autogain.load_config")
@patch("alexa_custom.autogain.init_engine")
@patch("alexa_custom.autogain.get_engine")
@patch("alexa_custom.autogain.get_stt_backend")
@patch("alexa_custom.autogain._capture_and_transcribe")
@patch("alexa_custom.autogain.set_input_gain")
@patch("alexa_custom.autogain.time.sleep")
def test_dry_run_skips_write(
    mock_sleep,
    mock_set_gain,
    mock_capture,
    mock_get_stt,
    mock_get_engine,
    mock_init_engine,
    mock_load_config,
    mock_load_secrets,
    mock_save,
    capsys,
):
    mock_load_config.return_value = _mock_config()
    mock_tts = MagicMock()
    mock_get_engine.return_value = mock_tts
    mock_capture.return_value = ("ascolta assistente chiama aiuto", b"\x00\x00" * 8000)

    with patch.object(sys, "argv", ["alexa-autogain", "--dry-run"]):
        main()

    captured = capsys.readouterr()
    assert "dry-run, non salvato" in captured.out
    mock_save.assert_not_called()


@patch("alexa_custom.autogain._save_gain_to_config")
@patch("alexa_custom.autogain.load_secrets")
@patch("alexa_custom.autogain.load_config")
@patch("alexa_custom.autogain.init_engine")
@patch("alexa_custom.autogain.get_engine")
@patch("alexa_custom.autogain.get_stt_backend")
@patch("alexa_custom.autogain._capture_and_transcribe")
@patch("alexa_custom.autogain.set_input_gain")
@patch("alexa_custom.autogain.time.sleep")
def test_custom_text_used(
    mock_sleep,
    mock_set_gain,
    mock_capture,
    mock_get_stt,
    mock_get_engine,
    mock_init_engine,
    mock_load_config,
    mock_load_secrets,
    mock_save,
    capsys,
):
    mock_load_config.return_value = _mock_config()
    mock_tts = MagicMock()
    mock_get_engine.return_value = mock_tts
    mock_capture.return_value = ("ascolta assistente chiama aiuto", b"\x00\x00" * 8000)

    custom = "ciao mondo"
    with patch.object(sys, "argv", ["alexa-autogain", "--text", custom]):
        main()

    _ = capsys.readouterr()
    say_calls = mock_tts.say.call_args_list
    say_texts = [c[0][0] for c in say_calls]
    assert any(custom in t for t in say_texts)
    assert mock_capture.call_count == 22  # 5 coarse×2 + 3 extension×2 + 3 zoom×2 (custom text has low similarity)


@patch("alexa_custom.autogain._save_gain_to_config")
@patch("alexa_custom.autogain.load_secrets")
@patch("alexa_custom.autogain.load_config")
@patch("alexa_custom.autogain.init_engine")
@patch("alexa_custom.autogain.get_engine")
@patch("alexa_custom.autogain.get_stt_backend")
@patch("alexa_custom.autogain._capture_and_transcribe")
@patch("alexa_custom.autogain.set_input_gain")
@patch("alexa_custom.autogain.time.sleep")
<<<<<<< HEAD
def test_summary_contains_coarse_gains(
=======
def test_all_gains_in_summary(
>>>>>>> 73b63b7 (refactor: autogain redesign - test all gains at all distances)
    mock_sleep,
    mock_set_gain,
    mock_capture,
    mock_get_stt,
    mock_get_engine,
    mock_init_engine,
    mock_load_config,
    mock_load_secrets,
    mock_save,
    capsys,
):
    mock_load_config.return_value = _mock_config()
    mock_tts = MagicMock()
    mock_get_engine.return_value = mock_tts
    mock_capture.return_value = ("ascolta assistente chiama aiuto", b"\x00\x00" * 8000)

    with patch.object(sys, "argv", ["alexa-autogain"]):
        main()

    captured = capsys.readouterr()
<<<<<<< HEAD
    for gain in [0.05, 0.15, 0.4, 1.0, 3.0]:
        assert f"{gain:.2f}" in captured.out or f" {gain}" in captured.out


# ── Auto mode tests ─────────────────────────────────────────────────────


class TestPinkNoiseReproducibility:
    def test_seeded_pink_noise_is_deterministic(self):
        a = _generate_pink_noise(1.0, 16000)
        b = _generate_pink_noise(1.0, 16000)
        assert np.array_equal(a, b)

    def test_different_duration_produces_different_length(self):
        a = _generate_pink_noise(0.5, 16000)
        b = _generate_pink_noise(1.0, 16000)
        assert len(a) == 8000
        assert len(b) == 16000


class TestFrequencyWeightedSNR:
    def test_speech_band_has_higher_weight(self):
        n = 16000
        low_noise = (
            np.sin(2 * np.pi * 100 * np.arange(n) / 16000).astype(np.float32) * 1000
        )
        speech_signal = (
            np.sin(2 * np.pi * 1000 * np.arange(n) / 16000).astype(np.float32) * 1000
        )
        noise_rms = 0.001
        low_snr = _compute_frequency_weighted_snr(low_noise, noise_rms)
        speech_snr = _compute_frequency_weighted_snr(speech_signal, noise_rms)
        assert speech_snr > low_snr

    def test_very_short_signal_returns_zero(self):
        short = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert _compute_frequency_weighted_snr(short, 0.001) == 0.0


class TestChannelBalance:
    def test_balanced_channels_return_zero(self):
        multi = np.column_stack([np.ones(100) * 1000, np.ones(100) * 1000])
        assert _compute_channel_balance(multi) < 1.0

    def test_unbalanced_channels_return_high_ratio(self):
        multi = np.column_stack([np.ones(100) * 10000, np.ones(100) * 10])
        ratio = _compute_channel_balance(multi)
        assert ratio > 6.0

    def test_mono_returns_zero(self):
        assert _compute_channel_balance(np.zeros((100, 1))) == 0.0


class TestSelectBestGain:
    def _make_vol(self, **kwargs):
        return {
            "snr_db": kwargs.get("snr_db", 20.0),
            "headroom_db": kwargs.get("headroom_db", 12.0),
            "clipping": kwargs.get("clipping", 0.0),
        }

    def _make_entry(
        self, gain, snr_db=20.0, headroom_db=12.0, clipping=0.0, imbalance=0.0
    ):
        multi = (
            np.ones((1, 2)) * 1000
            if imbalance < 6.0
            else np.column_stack([np.ones(100) * 10000, np.ones(100) * 10])
        )
        return {
            "gain": gain,
            "weighted_snr": snr_db,
            "volumes": {
                "lontano": self._make_vol(
                    snr_db=snr_db, headroom_db=headroom_db, clipping=clipping
                ),
                "medio": self._make_vol(
                    snr_db=snr_db + 1, headroom_db=headroom_db, clipping=clipping
                ),
                "vicino": self._make_vol(
                    snr_db=snr_db + 2, headroom_db=headroom_db, clipping=clipping
                ),
            },
            "_multi": multi,
        }

    def test_clear_winner(self):
        results = [
            self._make_entry(0.5, snr_db=15.0),
            self._make_entry(1.0, snr_db=25.0),
            self._make_entry(2.0, snr_db=30.0),
        ]
        assert _select_best_gain(results) == 2.0

    def test_headroom_filter(self):
        results = [
            self._make_entry(0.5, snr_db=20.0, headroom_db=12.0),
            self._make_entry(1.0, snr_db=40.0, headroom_db=3.0),
        ]
        assert _select_best_gain(results) == 0.5

    def test_clipping_filter(self):
        results = [
            self._make_entry(0.5, snr_db=10.0, clipping=0.0),
            self._make_entry(1.0, snr_db=50.0, clipping=0.05),
        ]
        assert _select_best_gain(results) == 0.5

    def test_channel_balance_penalty(self):
        multi_balanced = np.ones((100, 2)) * 1000
        multi_unbalanced = np.column_stack([np.ones(100) * 10000, np.ones(100) * 10])
        results = [
            {
                "gain": 0.5,
                "weighted_snr": 20.0,
                "volumes": {
                    "lontano": self._make_vol(
                        snr_db=20.0, headroom_db=12.0, clipping=0.0
                    ),
                    "medio": self._make_vol(
                        snr_db=21.0, headroom_db=12.0, clipping=0.0
                    ),
                    "vicino": self._make_vol(
                        snr_db=22.0, headroom_db=12.0, clipping=0.0
                    ),
                },
                "_multi": multi_balanced,
            },
            {
                "gain": 1.0,
                "weighted_snr": 25.0,
                "volumes": {
                    "lontano": self._make_vol(
                        snr_db=25.0, headroom_db=12.0, clipping=0.0
                    ),
                    "medio": self._make_vol(
                        snr_db=26.0, headroom_db=12.0, clipping=0.0
                    ),
                    "vicino": self._make_vol(
                        snr_db=27.0, headroom_db=12.0, clipping=0.0
                    ),
                },
                "_multi": multi_unbalanced,
            },
        ]
        chosen = _select_best_gain(results)
        assert chosen == 0.5

    def test_all_fail_fallback(self):
        results = [
            self._make_entry(0.5, snr_db=5.0, headroom_db=2.0, clipping=0.02),
            self._make_entry(1.0, snr_db=10.0, headroom_db=1.0, clipping=0.03),
        ]
        chosen = _select_best_gain(results)
        assert chosen == 1.0  # higher snr wins


class TestRunAutogainAutoIntegration:
    def _mock_actions_config(self):
        cfg = MagicMock()
        cfg.audio.input_device = "default_mic"
        cfg.tts.backend = "piper"
        cfg.tts.voice = "it-paola"
        cfg.tts.preroll_ms = 400
        cfg.recognition.wake_tone = "wake"
        cfg.stt.stage1 = MagicMock()
        cfg.wake_words = []
        return cfg

    @patch("alexa_custom.autogain._measure_noise_floor")
    @patch("alexa_custom.autogain._capture_playback_response")
    @patch("alexa_custom.autogain._save_gain_to_config")
    @patch("alexa_custom.autogain.set_input_gain")
    @patch("alexa_custom.autogain.time.sleep")
    def test_autogain_auto_dry_run(
        self, mock_sleep, mock_set_gain, mock_save, mock_capture, mock_noise
    ):
        from alexa_custom.autogain import run_autogain_auto

        mock_noise.return_value = [0.001]
        n = 16000
        mock_capture.return_value = (
            np.random.randn(n, 1).astype(np.float32) * 500,
            [0.5],
        )

        with patch(
            "alexa_custom.autogain.resolve_capture_source", return_value=(None, 1)
        ):
            with patch("alexa_custom.autogain._write_pink_noise_wav"):
                with patch("alexa_custom.autogain._scale_wav_to_playback_volume"):
                    result = run_autogain_auto(
                        self._mock_actions_config(), dry_run=True
                    )

        assert isinstance(result, float)
        assert 0.1 <= result <= 6.0
        mock_save.assert_not_called()

    @patch("alexa_custom.autogain._run_stt_validation")
    @patch("alexa_custom.autogain._measure_noise_floor")
    @patch("alexa_custom.autogain._capture_playback_response")
    @patch("alexa_custom.autogain._save_gain_to_config")
    @patch("alexa_custom.autogain.set_input_gain")
    @patch("alexa_custom.autogain.time.sleep")
    def test_autogain_auto_writes_config(
        self, mock_sleep, mock_set_gain, mock_save, mock_capture, mock_noise, mock_stt
    ):
        from alexa_custom.autogain import run_autogain_auto

        mock_noise.return_value = [0.001]
        n = 16000
        mock_capture.return_value = (
            np.random.randn(n, 1).astype(np.float32) * 500,
            [0.5],
        )
        mock_stt.return_value = True

        with patch(
            "alexa_custom.autogain.resolve_capture_source", return_value=(None, 1)
        ):
            with patch("alexa_custom.autogain._write_pink_noise_wav"):
                with patch("alexa_custom.autogain._scale_wav_to_playback_volume"):
                    result = run_autogain_auto(
                        self._mock_actions_config(), dry_run=False
                    )

        mock_save.assert_called_once()
        assert 0.1 <= result <= 6.0
=======
    for gain in TEST_GAINS:
        assert f"{gain:.2f}" in captured.out
<<<<<<< HEAD
>>>>>>> 73b63b7 (refactor: autogain redesign - test all gains at all distances)
=======


# ── Acoustic pipeline tests ──────────────────────────────────────────


def test_generate_pink_noise_shape():
    samples = _generate_pink_noise(1.0, 16000)
    assert isinstance(samples, np.ndarray)
    assert samples.dtype == np.int16
    assert len(samples) == 16000


def test_generate_pink_noise_normalized():
    samples = _generate_pink_noise(1.0, 16000)
    max_val = np.max(np.abs(samples.astype(np.int32)))
    assert max_val <= 32767
    assert max_val > 100


def test_generate_pink_noise_not_silent():
    s1 = _generate_pink_noise(1.0, 16000)
    s2 = _generate_pink_noise(1.0, 16000)
    assert not np.array_equal(s1, s2)


def test_write_pink_noise_wav():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        sr = _write_pink_noise_wav(path)
        with wave.open(path, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == sr
            assert wf.getnframes() > 0
            frames = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        assert len(frames) == int(sr * 1.0)
        fade_len = int(50 * sr / 1000)
        assert abs(int(frames[0])) < abs(int(frames[fade_len]))
        assert abs(int(frames[-1])) < abs(int(frames[-(fade_len + 1)]))
    finally:
        import os as _os
        _os.unlink(path)


def test_write_pink_noise_wav_not_silent():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        _write_pink_noise_wav(path)
        with wave.open(path, "rb") as wf:
            frames = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        assert np.max(np.abs(frames.astype(np.int32))) > 100
    finally:
        import os as _os
        _os.unlink(path)


def test_scale_wav_to_playback_volume():
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        src = f.name
    dst = src.replace(".wav", "_scaled.wav")
    try:
        _write_pink_noise_wav(src)
        _scale_wav_to_playback_volume(src, dst, volume=0.5)
        with wave.open(src, "rb") as wf:
            orig = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        with wave.open(dst, "rb") as wf:
            scaled = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        assert len(scaled) == len(orig)
        assert np.max(np.abs(scaled.astype(np.int32))) <= np.max(np.abs(orig.astype(np.int32)))
    finally:
        import os as _os
        for p in [src, dst]:
            try:
                _os.unlink(p)
            except OSError:
                pass


def test_analyze_channel_known_signal():
    t = np.linspace(0, 1, 16000, endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 0.5 * 32767).astype(np.float32)
    result = _analyze_channel(sine, noise_rms=0.01)
    assert result["clipping"] < 0.01
    assert result["headroom_db"] > 3.0
    assert result["snr_db"] > 20.0
    assert 0 < result["rms"] < 1.0
    assert 0 < result["peak"] < 1.0


def test_analyze_channel_silence():
    silence = np.zeros(16000, dtype=np.float32)
    result = _analyze_channel(silence, noise_rms=0.001)
    assert result["rms"] == 0.0
    assert result["peak"] == 0.0
    assert result["clipping"] == 0.0


def test_analyze_channel_clipping():
    clipped = np.full(16000, 32767.0, dtype=np.float32)
    result = _analyze_channel(clipped, noise_rms=0.001)
    assert result["clipping"] > 0.99
    assert result["peak"] == pytest.approx(1.0, rel=1e-3)


def _make_vol(v: dict) -> dict:
    return {
        "lontano": {"snr_db": v.get("snr_db_far", v["snr_db"]), "headroom_db": v["headroom_db"], "clipping": v["clipping"], "peaks": [0.5]},
        "medio": {"snr_db": v["snr_db"], "headroom_db": v["headroom_db"], "clipping": v["clipping"], "peaks": [0.5]},
        "vicino": {"snr_db": v.get("snr_db_near", v["snr_db"]), "headroom_db": v["headroom_db"], "clipping": v["clipping"], "peaks": [0.5]},
    }


def test_select_best_gain_clear_winner():
    results = [
        {"gain": 0.5, "weighted_snr": 15.0, "volumes": _make_vol({"snr_db": 15.0, "headroom_db": 10.0, "clipping": 0.0})},
        {"gain": 1.0, "weighted_snr": 25.0, "volumes": _make_vol({"snr_db": 25.0, "headroom_db": 8.0, "clipping": 0.0})},
        {"gain": 2.0, "weighted_snr": 30.0, "volumes": _make_vol({"snr_db": 30.0, "headroom_db": 6.0, "clipping": 0.0})},
    ]
    assert _select_best_gain(results) == 2.0


def test_select_best_gain_headroom_filter():
    results = [
        {"gain": 0.5, "weighted_snr": 20.0, "volumes": _make_vol({"snr_db": 20.0, "headroom_db": 12.0, "clipping": 0.0})},
        {"gain": 1.0, "weighted_snr": 40.0, "volumes": _make_vol({"snr_db": 40.0, "headroom_db": 3.0, "clipping": 0.0})},
    ]
    assert _select_best_gain(results) == 0.5


def test_select_best_gain_clipping_filter():
    results = [
        {"gain": 0.5, "weighted_snr": 10.0, "volumes": _make_vol({"snr_db": 10.0, "headroom_db": 12.0, "clipping": 0.0})},
        {"gain": 1.0, "weighted_snr": 50.0, "volumes": _make_vol({"snr_db": 50.0, "headroom_db": 1.0, "clipping": 0.05})},
    ]
    assert _select_best_gain(results) == 0.5


def test_select_best_gain_all_fail_fallback():
    results = [
        {"gain": 0.5, "weighted_snr": 5.0, "volumes": _make_vol({"snr_db": 5.0, "headroom_db": 2.0, "clipping": 0.02})},
        {"gain": 1.0, "weighted_snr": 10.0, "volumes": _make_vol({"snr_db": 10.0, "headroom_db": 1.0, "clipping": 0.03})},
    ]
    chosen = _select_best_gain(results)
    assert chosen == 1.0


def test_check_channel_balance_balanced():
    rng = np.random.default_rng(42)
    data = rng.standard_normal((1000, 2)).astype(np.float32) * 1000
    assert _check_channel_balance(data) is True


def test_check_channel_balance_imbalanced():
    data = np.zeros((1000, 2), dtype=np.float32)
    data[:, 0] = np.random.default_rng(42).standard_normal(1000) * 10000
    data[:, 1] = data[:, 0] * 0.01
    assert _check_channel_balance(data) is False


def test_check_channel_balance_mono():
    data = np.random.default_rng(42).standard_normal((1000, 1)).astype(np.float32)
    assert _check_channel_balance(data) is True


@patch("alexa_custom.autogain._capture_playback_response")
@patch("alexa_custom.autogain._measure_noise_floor")
@patch("alexa_custom.autogain._save_gain_to_config")
@patch("alexa_custom.autogain.set_input_gain")
@patch("alexa_custom.autogain.time.sleep")
def test_run_autogain_auto_confirmation_fallback(
    mock_sleep, mock_set_gain, mock_save, mock_noise, mock_capture
):
    mock_noise.return_value = [0.01]
    good_signal = (np.full((500, 1), 1000.0, dtype=np.float32), [1000.0 / 32768.0])
    bad_signal = (np.zeros((100, 1), dtype=np.float32), [0.0])
    mock_capture.side_effect = [good_signal] * 18 + [bad_signal, bad_signal]

    cfg = MagicMock()
    cfg.audio.input_device = "test_mic"
    cfg.wake_words = []

    with patch("alexa_custom.autogain.resolve_capture_source", return_value=(None, 1)):
        with patch("alexa_custom.autogain._write_pink_noise_wav"):
            with patch("alexa_custom.autogain._scale_wav_to_playback_volume"):
                result = run_autogain_auto(cfg, dry_run=True)

    assert result == 1.0


def _make_vol_entry(snr=20.0, headroom=10.0, clipping=0.0):
    return {"snr_db": snr, "headroom_db": headroom, "clipping": clipping, "peaks": [0.5]}


def test_print_acoustic_summary_exists():
    import io
    from contextlib import redirect_stdout

    vol_keys = [k for k, _, _ in _AUTO_PLAY_VOLUMES]
    results = [
        {"gain": 0.5, "weighted_snr": 15.0, "volumes": {k: _make_vol_entry(snr=10.0) for k in vol_keys}},
        {"gain": 1.0, "weighted_snr": 25.0, "volumes": {k: _make_vol_entry(snr=25.0) for k in vol_keys}},
    ]
    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_acoustic_summary(results, 1.0, dry_run=True)
    out = buf.getvalue()
    assert "multi-volume" in out
    assert "dry-run" in out


def test_print_acoustic_summary_labels():
    import io
    from contextlib import redirect_stdout

    vol_keys = [k for k, _, _ in _AUTO_PLAY_VOLUMES]
    vol = {k: _make_vol_entry() for k in vol_keys}
    results = [
        {"gain": 1.0, "weighted_snr": 20.0, "volumes": vol},
    ]
    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_acoustic_summary(results, 1.0, dry_run=False)
    out = buf.getvalue()
    assert "Lontano" in out
    assert "Medio" in out or "Media" in out
    assert "Vicino" in out
>>>>>>> db0c56e (fix: multi-volume playback with far-distance weighting in acoustic calibration)
