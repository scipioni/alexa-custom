---
name: tune-microphone
description: Auto-tune microphone and Speech-To-Text parameters (including input_gain) using a coordinate-descent search loop with serena-stt --score. Use this skill when the user wants to optimize sound capture, noise suppression, AGC, or RMS threshold settings for the speech recognition pipeline.
---

# Tune Microphone Skill

This skill guides the agent to systematically optimize the GStreamer capture pipeline and STT configurations on target hardware (such as the NewPie or Yealink) by executing `serena-stt --score` directly in its own conversational execution loop.

By performing coordinate-descent sweeps directly, the agent can analyze speech-matching results in real time, adjust variables dynamically, and arrive at the optimal acoustic parameters.

## Search Space Parameters
- `noise_suppression`: `[True, False]`
- `noise_suppression_level`: `[0, 1, 2, 3]`
- `agc`: `[True, False]`
- `agc_target_level_dbfs`: `[-3, -6, -10, -15]`
- `agc_compression_gain_db`: `[5, 9, 20, 40, 70]`
- `high_pass_filter`: `[True, False]`
- `rms_threshold`: `[0.005, 0.01, 0.02, 0.04]`
- `input_gain`: `[0.5, 1.0, 1.5, 2.0, 3.0]`

## Procedural Workflow for the Agent

When the user requests to optimize or tune the microphone:

### Phase 1: Initialize starting parameters from config files
1. Read `conf/state.yaml` and look up the active `gst_profile` (e.g. `yealink`).
2. Read `conf/config.yaml` to extract baseline configuration values:
   - Check the active GStreamer profile sections (`audio.gstreamer.profiles.<active_profile>`) for profile-specific values.
   - Fall back to base GStreamer configurations (`audio.gstreamer.*`).
   - Fall back to general defaults if not specified:
     - `noise_suppression`: true
     - `noise_suppression_level`: 2
     - `agc`: true
     - `agc_target_level_dbfs`: -3
     - `agc_compression_gain_db`: 9
     - `high_pass_filter`: true
     - `rms_threshold`: 0.02
     - `input_gain`: 1.0 (read from `conf/state.yaml`'s `input_gain` first, then `conf/config.yaml`'s `audio.input_gain`, then default to 1.0).
3. Log the resolved starting configuration as the "Baseline Parameters".

### Phase 2: Run Baseline Trial
1. Execute `serena-stt --score --timeout 15.0` with the Baseline Parameters:
   ```bash
   uv run serena-stt --score --timeout 15.0 \
     --[no-]noise-suppression --noise-suppression-level <val> \
     --[no-]agc --agc-target-level-dbfs <val> --agc-compression-gain-db <val> \
     --[no-]high-pass-filter --rms-threshold <val> --input-gain <val>
   ```
2. Parse the printed JSON output, and record the baseline score and text. This is your initial `best_score` and `best_params`.

### Phase 3: Run Coordinate-Descent Search Loop
Run consecutive optimization loops. For each parameter in the search space:
- Iterate through each candidate value (excluding the value that is already the current best for this parameter).
- Formulate a trial configuration where this parameter is swapped with the candidate value.
- Execute `serena-stt --score --timeout 15.0 <trial_params>` as a shell command.
- Parse the resulting JSON score and recognized text.
- Print a progress report on each trial:
  `Loop {loop_count}: Testing {param}={candidate} -> Score: {score} ({text})`
- If `score > best_score`, update `best_score` to the new score, update `best_params` for this parameter, and mark `improved = True`.
- Print:
  `Current Best Params: {best_params} (Best Score: {best_score})`

If a full pass over all parameters concludes with `improved == True`, repeat the loop. Otherwise, stop!

### Phase 4: Conclude & Output
1. Print the final optimal parameters in formatted YAML block so the user can easily copy them into `conf/config.yaml`.
2. Confirm the auto-tuning process is concluded successfully!
