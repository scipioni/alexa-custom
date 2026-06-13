## Why

The existing `alexa-mic-test` calibrates microphone gain using pink noise and acoustic metrics (SNR, headroom). This works but is blind to the actual STT model in use — a gain that maximizes SNR may not maximize transcription accuracy for a specific model (e.g., NeMo FastConformer CTC vs Vosk). Every time the STT model changes, the optimal gain can shift, requiring re-calibration. We need a calibration that optimizes for what actually matters: STT accuracy.

## What Changes

- New `alexa-mic-calibrate` CLI command that plays a pre-recorded speech WAV through the speaker, captures the acoustic loopback through the mic at multiple gain levels, transcribes each capture through the *currently configured* STT backend, scores by similarity to the expected phrase, and selects + persists the best gain
- Recorded test phrase WAV shipped in `models/test_phrase.wav`
- Internal refactoring: extract shared sweep/refinement/confirmation logic so `run_autogain_auto()` (pink noise) and the new model-aware calibrator share the same scaffolding

## Capabilities

### New Capabilities
- `auto-gain-calibration`: model-aware microphone gain calibration via acoustic loopback + real STT transcription scoring

### Modified Capabilities
*(none — net-new capability)*

## Impact

- **New file**: `models/test_phrase.wav` — pre-recorded Italian speech sample
- **Modified file**: `alexa_custom/autogain.py` — new entry point + shared sweep infrastructure
- **CLI**: new `alexa-mic-calibrate` entry point in `pyproject.toml`
- **Config**: no new config keys; uses existing `audio.input_gain` + `stt.stage2` backend
