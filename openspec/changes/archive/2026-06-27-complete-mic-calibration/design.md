## Context

Currently, the user can calibrate hardware input gain via the `calibrate_input_gain` voice command. However, GStreamer filters (Noise Suppression level, AGC, High-pass filter, etc.) are static and hardcoded in profiles. To maximize speech-to-text clarity dynamically, we need a complete calibration routine that tunes GStreamer parameters in addition to input gain.

## Goals / Non-Goals

**Goals:**
- Implement a new `calibrate_microphone_complete` action.
- Ensure the calibration dynamically re-evaluates both input gain and GStreamer noise suppression/AGC configurations.
- Persist winning GStreamer filter parameters natively under `conf/state.yaml` so they are applied at startup.

**Non-Goals:**
- Designing new GStreamer elements (only tuning existing ones like `webrtcdsp`).
- Bypassing the core GStreamer pipeline architecture.

## Decisions

### 1. Unified Multi-Stage Sweep Flow
- **Stage 1 (Gain Sweep)**: Reuse the existing 5-probe adaptive gain sweep.
- **Stage 2 (Filter Sweep)**: At the winning gain, dynamically spin up GStreamer capture pipelines with three candidate configurations (Standard, Sensitive, and DSP Bypass), capture the repeated phrase, and score them using Levenshtein distance.
- **Why**: Isolating the sweeps prevents multidimensional search space explosion, keeping the entire voice interaction short and convenient (8 probes total).

### 2. Isolated GStreamer Pipeline Probing
- **Approach**: For each GStreamer filter probe, the action starts an isolated `gst-launch` or pulsesrc capture subprocess using custom configurations (similar to `--calibrate-gstreamer` mode), reads the stream, and scores it.
- **Why**: Running isolated probes prevents having to dynamically hot-reload the main background daemon's stream mid-sentence, ensuring absolute stability.

### 3. State Persistence under `conf/state.yaml`
- **Approach**: Save the winning GStreamer overrides under a new `gstreamer_override` YAML key in `conf/state.yaml`.
- **Why**: Keeps the user's calibration fully decoupled from git-tracked code configurations and ensures the settings are automatically restored on every reboot.

## Risks / Trade-offs

- **[Risk]** Dynamic audio device access during sweeps could conflict with the background listening loop.
  - **Mitigation**: Temporarily pause or release the background STT capture pipeline when the calibration action is active.
