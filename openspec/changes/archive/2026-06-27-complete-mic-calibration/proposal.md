## Why

Currently, Serena supports automatic microphone input gain calibration (`calibrate_input_gain`). However, optimal voice recognition depends heavily on tuning other GStreamer pipeline parameters (such as noise suppression, high-pass filter cutoff, and WebRTC digital AGC compression gain). Introducing a unified voice command to completely calibrate both the hardware gain and GStreamer voice filters will maximize accuracy and clarity on different sound cards without manual SSH debugging.

## What Changes

- **New Action Type**: Register a new action type `calibrate_microphone_complete` in the action registry.
- **Unified Calibration Routine**: This action will run a multi-stage calibration:
  1. **Stage 1 (Gain Calibration)**: Performs the adaptive 5-probe input gain sweep (matching `calibrate_input_gain`).
  2. **Stage 2 (GStreamer Filters Tuning)**: Performs a multi-probe parameter sweep over GStreamer WebRTC DSP parameters (including `noise_suppression_level` and `agc_compression_gain_db`) while playing prompts and prompting the user to repeat.
- **State Persistence**: Persists the winning GStreamer parameters under a dedicated calibrated profile (or overrides the active state configuration) in `conf/state.yaml`.
- **Config & CLI Integration**: Integrates the complete calibration with hot-reloading configurations and CLI overrides.

## Capabilities

### New Capabilities
- `complete-microphone-calibration`: Establishes the new automatic, multi-stage hardware gain and GStreamer pre-processing parameter calibration routine.

### Modified Capabilities
- `input-gain-calibration`: Extends or links the gain-level calibration requirements to be reusable inside the complete calibration routine.

## Impact

- **Affected Code**: `alexa_custom/actions.py` (for action registration and logic), `alexa_custom/audio_hw.py` and `alexa_custom/config.py` (for state and config parsing), `alexa_custom/stt.py` (for dynamic pipeline restarts during calibration probes).
- **APIs & Configs**: New `calibrate_microphone_complete` action entry type in `conf/actions/user.yaml`.
- **Testing**: New unit tests in `tests/test_complete_calibration.py`.
