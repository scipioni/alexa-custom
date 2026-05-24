## Why

Vosk works but is heavier than necessary — the Italian model is ~50MB and CPU-intensive. For constrained setups (e.g., Linux host driving an Arduino Uno Q USB audio gadget), sherpa-onnx's Paraformer-ita model delivers equal or better accuracy at a fraction of the size (~15MB) and CPU load, reducing audio glitch risk under load.

Sherpa-onnx is not a replacement — it's a **configurable alternative** so users can choose based on their hardware.

## What Changes

- Add `stt.backend: sherpa-onnx` as a config option alongside existing Vosk
- Add sherpa-onnx Italian Paraformer model download via `alexa-setup`
- Abstract STT recognition behind a `STTBackend` interface (analogous to `TTSBackend`)
- Vosk remains the default; sherpa-onnx is opt-in
- No changes to the trigger/action pipeline

## Capabilities

### New Capabilities
- **sherpa-onnx-stt**: sherpa-onnx streaming STT as an alternative backend. When configured, `stt.py` uses the sherpa-onnx OnlineRecognizer instead of Vosk KaldiRecognizer. Includes VAD built into the model.

### Modified Capabilities
- *(none — Vosk behavior is unchanged; sherpa-onnx is purely additive)*

## Impact

- **New dependency**: `sherpa-onnx` Python package added to `pyproject.toml`
- **New model**: `models/sherpa-onnx/` directory for the Italian Paraformer ONNX files
- **Modified files**: `stt.py` (backend abstraction), `setup.py` (model download), `config.py` (stt.backend option), `config.yaml.example` (new option documented)
- **No breaking changes**: existing Vosk users see zero difference
