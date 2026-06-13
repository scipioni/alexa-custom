## Why

The sherpa-onnx transducer model (kroko_128l) is autoregressive and slow on the Arduino Uno Q's Cortex-A53 cores. A NeMo FastConformer CTC model (114M params, non-autoregressive) exists that supports Italian but requires offline (buffer-then-transcribe) inference. Creating an offline STT backend unlocks better accuracy with lower CPU usage.

## What Changes

1. **New `NeMoOfflineSTT` backend**: `STTBackend` subclass using `OfflineRecognizer.from_nemo_ctc()`, buffers audio in `accept_waveform()`, runs full transcription in `finalize()`
2. **Config schema**: Add `nemo-offline` as a valid stage2 backend
3. **Model download**: Update `alexa-setup --sherpa-onnx` to download the NeMo model to `models/sherpa-onnx/nemo-ctc-it/`
4. **No changes to STT orchestration**: Buffer-then-transcribe pattern already proven by `WhisperCppSTT`

## Capabilities

### New Capabilities
- `nemo-offline-stt`: Offline NeMo FastConformer CTC STT backend for stage 2 command transcription, using buffer-then-transcribe pattern with `OfflineRecognizer.from_nemo_ctc()`

### Modified Capabilities
- `sherpa-onnx-stt`: Update model download path for sherpa-onnx alternative models; add offline inference capability

## Impact

- `alexa_custom/stt_backends.py`: New `NeMoOfflineSTT` class, new `get_stt_backend()` branch for `"nemo-offline"`
- `alexa_custom/config.py`: Add `"nemo-offline"` to valid stage2 backends
- `alexa_custom/setup.py`: Update download path to `models/sherpa-onnx/nemo-ctc-it/` with `model.onnx` + `tokens.txt`
- `openspec/specs/sherpa-onnx-stt/spec.md`: Update model path and add offline inference requirements
