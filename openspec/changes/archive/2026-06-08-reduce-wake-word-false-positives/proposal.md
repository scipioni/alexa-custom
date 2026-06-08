## Why

Stage-1 wake-word detection produces too many false positives: the daemon wakes on other people's conversation and even mis-fires on the two-word proper-noun phrase "ehi galileo". Three causes are confirmed in code, but the deeper problem is that **false positives are not measurable today** — the existing `test-stt-e2e` harness only synthesises the wake word and checks recognition (true-positive/miss), so any tuning is a guess and regressions are invisible. We need to measure before we tune.

## What Changes

- **New false-positive / miss-rate eval harness.** Feed a labelled corpus of audio clips through the stage-1 pipeline with no microphone (offline, headless) and report **false-positives-per-hour** and **miss-rate** for a given backend/threshold/confidence-mode configuration. The harness sweeps configurations and emits a comparison table so the Vosk-vs-KWS decision becomes data-driven. The harness is retained as a permanent regression guard.
  - **Negative corpus** (must NOT wake): Italian conversation snippets, near-misses ("Gabriele", "galleria", "assistenza"), chatter/TV beds, and far-field/quiet (gain-attenuated) variants.
  - **Positive corpus** (SHOULD wake): "ehi galileo" synthesised across Piper voices/speeds and attenuation levels.
- **Stage-1 Vosk confidence fix.** Aggregate recognition confidence across **all tokens** of the matched wake phrase (not just the first word, `words[0]`). The discriminative token ("galileo") is currently never confidence-checked. Confidence mode is selectable to allow A/B measurement.
- **Stage-1 Vosk RMS pre-gate.** Apply an energy (`rms_threshold`) pre-gate to the Vosk branch so quiet far-field cross-talk never reaches the grammar decoder. Today `rms_threshold` only wires into the sherpa open-vocab path.
- **Data-driven KWS evaluation (no committed backend switch).** Run the existing sherpa-onnx KeywordSpotter stage-1 path through the same harness and compare tradeoff curves. This change does **not** change the default backend; it produces the evidence to decide later.

## Capabilities

### New Capabilities
- `wake-word-detection-eval`: Offline, microphone-free harness that scores stage-1 wake detection against labelled positive/negative audio corpora, reporting false-positives-per-hour and miss-rate per configuration and supporting configuration sweeps for backend comparison.

### Modified Capabilities
- `wake-word-detection`: Stage-1 Vosk acceptance now gates on aggregated multi-token confidence (configurable mode) and on an RMS energy pre-gate, tightening rejection of non-wake speech without changing the stage-1/stage-2 contract.

## Impact

- **Code**: `alexa_custom/stt.py` (stage-1 Vosk branch — confidence aggregation, RMS pre-gate). New eval harness module + CLI entry point (e.g. `alexa-wake-eval`) and/or a test skill. Possibly `alexa_custom/config.py` for a new `stt.stage1.confidence_mode` field.
- **Config**: `conf/config.yaml` gains an optional `stt.stage1.confidence_mode` key (`first` | `min` | `mean`); existing behaviour preserved when defaulted.
- **Dependencies**: Reuses Piper TTS (already present) for corpus synthesis; no new runtime dependency. Optionally pulls Italian Common Voice / recorded ambient clips as test fixtures (dev/test only).
- **Audio constraints**: Harness runs offline — no PortAudio playback/capture, honouring the board's audio limitations (CLAUDE.md).
- **Backwards compatibility**: Default detection behaviour is preserved unless the new confidence mode is explicitly configured; the KWS backend is not switched by default.
