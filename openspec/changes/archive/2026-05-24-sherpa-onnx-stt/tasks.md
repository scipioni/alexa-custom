## 1. Dependencies

- [x] 1.1 Add `sherpa-onnx>=1.0` to `pyproject.toml` dependencies

## 2. Model Download

- [ ] 2.1 Add `_SHERPA_MODELS` dict with Italian Paraformer model URL in `setup.py`
- [ ] 2.2 Add `download_sherpa_onnx()` function to `setup.py`
- [ ] 2.3 Add `--sherpa-onnx` CLI flag to `main()` in `setup.py`
- [ ] 2.4 Add `--no-sherpa-onnx` flag (default: False)

## 3. Config

- [ ] 3.1 Add `stt.backend: str` field to `ActionsConfig` in `config.py` (default: `"vosk"`)
- [ ] 3.2 Add `stt:` block parsing in `_parse_actions_config()` with `backend` and `model_path` keys
- [ ] 3.3 Update `config.yaml.example` to document `stt.backend: vosk | sherpa-onnx`

## 4. STT Backend Abstraction

- [ ] 4.1 Add abstract `STTBackend` class in `stt.py` with methods: `accept_waveform`, `text`, `partial_text`, `reset`
- [ ] 4.2 Wrap existing Vosk logic in `VoskSTT` class implementing `STTBackend`
- [ ] 4.3 Add `SherpaOnnxSTT` class implementing `STTBackend` using `sherpa_onnx.OnlineRecognizer`
- [ ] 4.4 Add `get_stt_backend()` factory that returns the configured backend instance

## 5. Integrate Backend Selection

- [ ] 5.1 Modify `run_stt_worker()` in `stt.py` to call `get_stt_backend()` instead of directly creating Vosk objects
- [ ] 5.2 Add `VOSK_MODEL_PATH` and `SHERPA_MODEL_PATH` env vars for model locations
- [ ] 5.3 Add graceful error handling when sherpa-onnx model is missing but backend is set to sherpa-onnx

## 6. Tests

- [ ] 6.1 Add unit tests for `STTBackend` factory and backend selection logic
- [ ] 6.2 Add integration test for sherpa-onnx backend (mock or skip if model absent)
- [ ] 6.3 Run `task fix` and ensure all existing tests pass
