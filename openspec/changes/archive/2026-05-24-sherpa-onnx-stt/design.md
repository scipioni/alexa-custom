## Context

The current STT pipeline in `stt.py` is tightly coupled to Vosk's `KaldiRecognizer`. The `wake-word-detection` spec requires "Vosk grammar-mode recognition" — an implementation detail baked into the requirements. Adding sherpa-onnx as an alternative means decoupling the STT interface from the Vosk-specific internals, while keeping the same behavioral contract.

Sherpa-onnx's Paraformer-ita is a self-contained streaming E2E model (~15MB) that includes VAD + ASR in one. It accepts raw 16kHz mono int16 audio and emits text incrementally — functionally equivalent to Vosk's `AcceptWaveform` / `PartialResult` / `Result` cycle.

## Goals / Non-Goals

**Goals:**
- Add sherpa-onnx as a selectable STT backend via `config.yaml`
- Maintain identical wake-word-detection behavior regardless of backend
- Keep Vosk as the default; sherpa-onnx users opt in explicitly
- Minimal diff — don't rewrite `stt.py`, just add a backend abstraction layer

**Non-Goals:**
- Replacing Vosk or deprecating it
- Supporting cloud STT backends (only local models)
- Supporting languages other than Italian for sherpa-onnx (future work)

## Decisions

### Decision 1: Backend abstraction via a `STTBackend` interface

**Choice:** Add an abstract `STTBackend` class with `accept_waveform`, `text`, `partial_text`, and `reset` methods. Vosk and SherpaOnnx implement it.

**Alternatives considered:**
- *Replace Vosk callsites wholesale* — too risky, too many call sites
- *Factory function with if/else* — works short-term but grows unwieldy as backends grow

**Rationale:** Follows the same pattern as `TTSBackend` in `tts.py`. Clear, testable, easy to add backends later.

---

### Decision 2: Sherpa-onnx model — `sherpa-onnx-paraformer-ita`

**Choice:** `sherpa-onnx-paraformer-ita` from the sherpa-onnx GitHub releases.

**Alternatives considered:**
- *sherpa-onnx-nemo-rnnt-ita* — RNNT model, larger, higher latency, overkill for wake word
- *whisper.cpp* — good quality but no streaming/partial results, not suitable for real-time wake word

**Rationale:** Paraformer is streaming, small (~15MB), fast, and has Italian support. It's the recommended sherpa-onnx model for this use case.

---

### Decision 3: Config key — `stt.backend: vosk | sherpa-onnx`

**Choice:** Top-level `stt:` block in `config.yaml` with `backend` key.

```yaml
stt:
  backend: sherpa-onnx  # or vosk (default)
```

**Alternatives considered:**
- *Flat key like `stt_backend`* — less extensible
- *Nested under `stt` with `model` sub-key* — already using this pattern for `tts:` so consistent

**Rationale:** Consistent with existing `tts:` section shape (`tts.backend`, `tts.voice`).

---

### Decision 4: Model download — same `alexa-setup` CLI

**Choice:** Extend `setup.py` with `--sherpa-onnx` flag; model stored in `models/sherpa-onnx/`.

**Alternatives considered:**
- *Separate `alexa-setup-sherpa` script* — more CLI surface, unnecessary
- *Auto-download on first run* — explicit is better; user should control when GB-scale downloads happen

**Rationale:** Single setup entry point, consistent with Vosk/Piper download pattern.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| sherpa-onnx partial result timing differs from Vosk | Tune `_VAD_SILENCE_MS` env var independently per backend |
| Model file URL goes stale | Pin to GitHub release tag, not `latest` |
| Wake word grammar constraint not supported by sherpa-onnx Paraformer | Paraformer is open-vocabulary — no grammar needed; config unchanged |
| Concurrent backends (both downloaded) waste disk | Each is ~15-50MB, acceptable; user chooses one |

## Open Questions

1. **Hot-reload**: Does switching `stt.backend` mid-run require a restart? (Vosk does — same should apply to sherpa-onnx; document it.)
2. **VAD mode**: Sherpa-onnx Paraformer has internal VAD. Should we expose `vad_mode` as a config option, or always use the default?
3. **Partial results**: Vosk emits partial text during recognition. Sherpa-onnx Paraformer's `text` property returns results incrementally — same behavior, but need to verify latency is acceptable for the UI "transcribing" state.
