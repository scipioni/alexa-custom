"""Fast, model-free unit tests for the sherpa-onnx STT backend selection path.

Deliberately does NOT load real Kroko/Silero models (40-50s, ~300MB) — those
are exercised via scripts/bench_stt.py on real hardware instead (see
docs/asr-plan.md and openspec/changes/add-sherpa-onnx-stt-backend). This file
only covers backend-selection/error-handling logic that runs before any model
file is touched.
"""

from __future__ import annotations

import pytest

from alexa_custom.config import STTConfig
from alexa_custom.stt_backends import (
    _check_sherpa_onnx_files,
    get_stt_backend,
)


class TestSherpaOnnxModelFilesCheck:
    def test_missing_model_dir_raises_clear_error(self, tmp_path):
        with pytest.raises(RuntimeError, match="serena-setup --sherpa-onnx-model"):
            _check_sherpa_onnx_files(
                str(tmp_path / "does-not-exist"), str(tmp_path / "silero_vad.onnx")
            )

    def test_missing_vad_model_raises_clear_error(self, tmp_path):
        model_dir = tmp_path / "kroko_64l"
        model_dir.mkdir()
        for name in (
            "tokens.txt",
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
        ):
            (model_dir / name).write_bytes(b"x")

        with pytest.raises(RuntimeError, match="Silero VAD model not found"):
            _check_sherpa_onnx_files(str(model_dir), str(tmp_path / "silero_vad.onnx"))

    def test_complete_files_pass_the_check(self, tmp_path):
        model_dir = tmp_path / "kroko_64l"
        model_dir.mkdir()
        for name in (
            "tokens.txt",
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
        ):
            (model_dir / name).write_bytes(b"x")
        vad_path = tmp_path / "silero_vad.onnx"
        vad_path.write_bytes(b"x")

        _check_sherpa_onnx_files(str(model_dir), str(vad_path))  # no raise


class TestGetSttBackend:
    def test_default_backend_is_vosk(self, tmp_path):
        # Nonexistent model_path so _load_model's own directory-existence
        # check fires — confirms the "vosk" branch is what ran, without
        # needing a real model to load.
        cfg = STTConfig(model_path=str(tmp_path / "nonexistent"))
        with pytest.raises(RuntimeError, match="Vosk model not found"):
            get_stt_backend(cfg)

    def test_sherpa_onnx_missing_files_raises_before_import(self, tmp_path):
        """Model-file check must run (and fail clearly) even if sherpa_onnx
        the Python package happens to be installed — this board has it
        installed for asr_eval.py, so this guards against accidentally
        skipping the file-existence check."""
        cfg = STTConfig(backend="sherpa-onnx", model_path=str(tmp_path / "missing"))
        with pytest.raises(RuntimeError, match="serena-setup --sherpa-onnx-model"):
            get_stt_backend(cfg)
