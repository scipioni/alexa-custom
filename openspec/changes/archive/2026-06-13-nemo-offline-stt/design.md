## Context

The board has a NeMo FastConformer CTC model (114M params, multilingual incl. Italian, ~461MB) already downloaded at `models/sherpa-onnx/nemo-ctc-it/`. This model is an offline CTC model — it expects full audio at once, not streaming. The `sherpa-onnx` library provides `OfflineRecognizer.from_nemo_ctc()` for this purpose.

The existing `WhisperCppSTT` backend already demonstrates the buffer-then-transcribe pattern: audio chunks are accumulated in `accept_waveform()`, and inference runs in `finalize()`. This pattern maps directly to offline recognizers.

## Goals / Non-Goals

**Goals:**
- Add `NeMoOfflineSTT` backend using `sherpa_onnx.OfflineRecognizer.from_nemo_ctc()`
- Buffer all audio chunks during stage-2 capture, transcribe in `finalize()`
- Register backend as `nemo-offline` in config and factory
- Default model path: `models/sherpa-onnx/nemo-ctc-it/`
- Download via `alexa-setup --sherpa-onnx`

**Non-Goals:**
- Not changing the `STTBackend` interface or `stt.py` orchestration
- Not adding streaming/partial results (offline-only)
- Not modifying Vosk or other backends

## Decisions

### Decision 1: OfflineRecognizer over OnlineRecognizer

**Choice**: Use `sherpa_onnx.OfflineRecognizer.from_nemo_ctc()`.

**Rationale**: The NeMo model lacks streaming metadata (`window_size`, cache dims) needed by `OnlineRecognizer.from_nemo_ctc()`. It works correctly with `OfflineRecognizer.from_nemo_ctc()` which does not require those fields.

### Decision 2: Buffer-then-transcribe pattern (same as WhisperCppSTT)

**Choice**: `accept_waveform()` buffers int16 PCM, `finalize()` concatenates, converts to float32, and runs full transcription.

**Rationale**: 
- `OfflineRecognizer` accepts a single `OfflineStream` with the complete audio
- Same pattern proven by `WhisperCppSTT` — no orchestration changes needed
- No endpoint detection complexity

### Decision 3: Single model directory under `models/sherpa-onnx/nemo-ctc-it/`

**Choice**: Store the NeMo model at `models/sherpa-onnx/nemo-ctc-it/` with `model.onnx` + `tokens.txt`.

**Rationale**: Keeps sherpa-onnx models organized under a common tree, separate from Vosk (`models/it/`).

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| 461MB model may be slow to load on 4GB board | FastConformer is non-autoregressive; inference is single-pass and fast |
| OfflineRecognizer API differs from backend interface | The buffer-then-transcribe pattern works naturally — feed full audio as float32 [-1,1] |
| CTG decode may have lower accuracy on Italian than transducer | This model was trained on ~20k hours of multilingual data including Italian; test on board before shipping |
| No partial results during capture | Acceptable trade-off for stage 2; user gets response after processing completes |

## Open Questions

- What is the real-time factor on Cortex-A53 with this model?
- Does vocab_size=2560 need +1 for blank token (handled by sherpa-onnx internally)?
