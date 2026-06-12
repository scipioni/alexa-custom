from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from alexa_custom.record import main


@patch("alexa_custom.record.load_secrets")
@patch("alexa_custom.record.load_config")
@patch("alexa_custom.record.init_engine")
@patch("alexa_custom.record.get_engine")
@patch("alexa_custom.record.get_stt_backend")
@patch("alexa_custom.record.resolve_capture_source")
@patch("alexa_custom.record.start_capture")
@patch("alexa_custom.record.set_input_gain")
@patch("alexa_custom.record.play_wake_beep")
@patch("alexa_custom.record.time.sleep")
def test_alexa_record_command(
    mock_sleep,
    mock_play_wake_beep,
    mock_set_input_gain,
    mock_start_capture,
    mock_resolve_capture_source,
    mock_get_stt_backend,
    mock_get_engine,
    mock_init_engine,
    mock_load_config,
    mock_load_secrets,
    tmp_path,
    capsys,
):
    # Mock Config
    mock_config = MagicMock()
    mock_config.tts.backend = "piper"
    mock_config.tts.voice = "it-paola"
    mock_config.tts.preroll_ms = 400
    mock_config.audio.input_device = "default_mic"
    mock_config.recognition.wake_tone = "wake"
    mock_config.stt.stage1 = MagicMock()
    mock_config.wake_words = []
    mock_load_config.return_value = mock_config

    # Mock TTS Engine
    mock_tts = MagicMock()
    mock_get_engine.return_value = mock_tts

    # Mock STT Backend
    mock_stt = MagicMock()
    mock_stt.finalize.return_value = "parlato di prova"
    mock_get_stt_backend.return_value = mock_stt

    # Mock Capture Source
    mock_resolve_capture_source.return_value = ("pw_source", 1)

    # Mock Capture Process
    mock_proc = MagicMock()
    mock_proc.stdout.read.return_value = b"\x00" * 4096
    mock_proc.poll.return_value = None
    mock_start_capture.return_value = mock_proc

    # Mock stdin/stdout timeout helper to return some bytes
    with patch(
        "alexa_custom.record._read_with_timeout"
    ) as mock_read_with_timeout:
        # Mock _read_with_timeout to return some mock raw data
        mock_read_with_timeout.side_effect = lambda stdout, nbytes, timeout: b"\x00" * nbytes

        out_file = tmp_path / "test_records.txt"
        test_text = "test_reference_text"

        test_args = [
            "alexa-record",
            "--duration",
            "0.1",
            "--out",
            str(out_file),
            "--text",
            test_text,
        ]

        with patch.object(sys, "argv", test_args):
            main()

    # Assert load_secrets and load_config called
    mock_load_secrets.assert_called_once_with("conf/secrets.yaml")
    mock_load_config.assert_called_once_with("conf/config.yaml")

    # Assert TTS init & get
    mock_init_engine.assert_called_once_with(
        backend_type="piper", voice="it-paola", preroll_ms=400
    )
    mock_get_engine.assert_called_once()

    # Assert set_input_gain was called 10 times (from 0.1 to 1.0)
    assert mock_set_input_gain.call_count == 10
    # First call with 0.1, last with 1.0
    mock_set_input_gain.assert_any_call(None, "default_mic", pytest.approx(0.1))
    mock_set_input_gain.assert_any_call(None, "default_mic", pytest.approx(1.0))

    # Assert say was called for each level
    assert mock_tts.say.call_count == 10
    mock_tts.say.assert_any_call("imposto il microfono a 0.1, prego registra testo per 0.1 secondi")
    mock_tts.say.assert_any_call("imposto il microfono a 1.0, prego registra testo per 0.1 secondi")

    # Assert play_wake_beep was called 10 times
    assert mock_play_wake_beep.call_count == 10
    mock_play_wake_beep.assert_any_call("wake")

    # Assert start_capture called 10 times
    assert mock_start_capture.call_count == 10
    mock_start_capture.assert_any_call("pw_source", 1)

    # Check that `--text` was printed to stdout 10 times
    captured = capsys.readouterr()
    assert captured.out.count(test_text) == 10

    # Check output file content
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    lines = content.strip().split("\n")

    # Line 1 is reference text
    assert lines[0] == f"testo riferimento: {test_text}"
    # Lines 1-10 are gain outputs
    assert len(lines) == 11
    assert lines[1] == "0.1 parlato di prova"
    assert lines[10] == "1.0 parlato di prova"
