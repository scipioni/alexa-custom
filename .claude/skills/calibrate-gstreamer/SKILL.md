---
name: calibrate-gstreamer
description: Systematic GStreamer parameter optimisation for the STT pipeline. Uses the serena-calibrate MCP server (keeps Vosk model resident — ~5 s faster per trial than the CLI). Sweeps parameters, scores each variant, and reports the best configuration as a YAML snippet.
license: MIT
metadata:
  author: stefano.scipioni@csgalileo.net
  version: "2.0"
---

Optimise GStreamer audio processing parameters for the Serena STT pipeline.

## Overview

Two modes of operation — **prefer MCP** (faster); fall back to CLI if the MCP server is unavailable.

### MCP mode (preferred)

The `serena-calibrate` MCP server keeps the Vosk model and TTS engine loaded between trials, saving ~5 s per trial.

**Tools exposed:**
| Tool | Purpose |
|---|---|
| `calibrate_init(phrase, listen_seconds?, rms_threshold?)` | Load config, Vosk model, TTS once. Call once per session. |
| `calibrate_trial(noise_suppression?, noise_suppression_level?, agc?, agc_target_level_dbfs?, agc_compression_gain_db?, high_pass_filter?, compressor?, compressor_threshold?, compressor_ratio?)` | Run one trial. Returns JSON result. |
| `calibrate_summary()` | Ranked table of all trials + winning YAML. |
| `calibrate_reset()` | Clear session state. |

### CLI fallback

```bash
uv run --active serena-stt --calibrate-gstreamer --phrase "TEXT" [gst flags…]
```

---

## JSON result fields (both modes)

| Field | Meaning |
|---|---|
| `exact_match` | `true` if the phrase was correctly identified |
| `match_score` | Fuzzy similarity score 0–100 |
| `speech_ratio` | Fraction of audio chunks above the RMS threshold — proxy for signal strength |
| `composite_score` | Ranking score: `(exact_match ? 60 : 0) + match_score * 0.3 + speech_ratio * 100` |
| `rms_peak` | Peak RMS across the capture window |
| `rms_mean` | Mean RMS |
| `transcript` | What Vosk actually heard |
| `gst_params` | The full parameter set used for this run |

**Composite score formula:**
```
score = (exact_match ? 60 : 0) + match_score * 0.3 + speech_ratio * 100
```
Maximum possible ≈ 160. Baseline with a quiet mic typically scores 30–70.

---

## Protocol

Use a **fixed phrase** for the entire session so results are comparable. Good choices:
- `"ehi serena volume alto"` — wake word + 2-word command, phonetically distinct
- `"che tempo farà domani"` — direct command, long enough to stress the pipeline

Tell the user which phrase to say **before starting**, then keep it consistent throughout.

**Ask the user to be ready** before every `calibrate_trial` call: they must speak the phrase within ~0.5 s after the ready tone. Remind them if a trial looks bad (`rms_peak < 0.005` = mic silent, discard; `captured_seconds < 3.0` = capture failure, skip).

---

## Step 1 — Baseline (3 trials)

### MCP

```
calibrate_init(phrase="ehi serena volume alto")
calibrate_trial()   ← trial 1 (all defaults)
calibrate_trial()   ← trial 2
calibrate_trial()   ← trial 3
```

### CLI fallback

```bash
uv run --active serena-stt --calibrate-gstreamer --phrase "ehi serena volume alto"
# repeat 3 times
```

Compute from the 3 results:
- `baseline_score` = average `composite_score`
- `baseline_speech_ratio` = average `speech_ratio`
- Note the typical `transcript`

If `rms_peak < 0.005` on any trial, the user missed the cue — discard and repeat.

---

## Step 2 — Boolean parameter ablation (1 trial each)

### MCP

```
calibrate_trial(noise_suppression=false)
calibrate_trial(noise_suppression_level=0)
calibrate_trial(noise_suppression_level=1)
calibrate_trial(noise_suppression_level=3)
calibrate_trial(agc=false)
calibrate_trial(high_pass_filter=false)
calibrate_trial(compressor=true)
```

### CLI fallback

```bash
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --no-noise-suppression
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --noise-suppression-level 0
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --noise-suppression-level 1
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --noise-suppression-level 3
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --no-agc
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --no-high-pass-filter
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --compressor
```

**Decision rule**: if a variant scores > `baseline_score + 5`, mark as a candidate improvement.

---

## Step 3 — Numeric parameter sweep

### MCP

```
calibrate_trial(agc_target_level_dbfs=-6)
calibrate_trial(agc_target_level_dbfs=-9)
calibrate_trial(agc_target_level_dbfs=-15)
calibrate_trial(agc_compression_gain_db=18)
calibrate_trial(agc_compression_gain_db=30)
```

If `baseline_speech_ratio < 0.20`, also sweep the compressor:

```
calibrate_trial(compressor=true, compressor_threshold=0.05, compressor_ratio=3.0)
calibrate_trial(compressor=true, compressor_threshold=0.10, compressor_ratio=5.0)
```

### CLI fallback

```bash
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --agc-target-level-dbfs -6
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --agc-target-level-dbfs -9
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --agc-target-level-dbfs -15
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --agc-compression-gain-db 18
uv run --active serena-stt --calibrate-gstreamer --phrase "..." --agc-compression-gain-db 30
```

---

## Step 4 — Best combination (3 trials)

Combine all flags that individually beat baseline by > 5 points. Run 3 trials to confirm.

### MCP

```
calibrate_trial(…all winning params combined…)   ← trial 1
calibrate_trial(…)   ← trial 2
calibrate_trial(…)   ← trial 3
calibrate_summary()   ← get ranked table + winning YAML
```

### CLI fallback

```bash
uv run --active serena-stt --calibrate-gstreamer --phrase "..." [all winning flags]
# repeat 3 times
```

Confirmed improvement if average composite score > `baseline_score + 10`.

---

## Step 5 — Report

Call `calibrate_summary()` (MCP) or build the table manually (CLI).

### Results table (example)
| Variant | Score | exact_match rate | speech_ratio | transcript sample |
|---|---|---|---|---|
| baseline | 52 | 1/3 | 0.12 | "volume alto" |
| agc=false | 38 | 0/3 | 0.08 | "borsa mondo" |
| noise_suppression_level=3 | 71 | 2/3 | 0.19 | "ehi serena volume" |
| agc_compression_gain_db=18 | 88 | 3/3 | 0.31 | "ehi serena volume alto" |
| best combo | 95 | 3/3 | 0.35 | "ehi serena volume alto" |

### Apply the winning config

`calibrate_summary()` returns `winning_config_yaml` — copy it into `conf/config.yaml` under the `audio.gstreamer` key:

```yaml
audio:
  gstreamer:
    source: pulsesrc
    noise_suppression: true
    noise_suppression_level: 3
    agc: true
    agc_target_level_dbfs: -9
    agc_compression_gain_db: 18
    high_pass_filter: true
    compressor: false
    compressor_threshold: 0.1
    compressor_ratio: 3.0
```

Also ensure `stt.capture_backend: gstreamer` is set, and remind the user to activate the updated profile:

```bash
# say (after wake word): "attiva microfono sensibile"
```

---

## Edge cases

- **`rms_peak < 0.005`**: User didn't speak or mic is unplugged. Discard and repeat.
- **`captured_seconds < 3.0`**: GStreamer failed to fill the buffer — usually a device routing issue, not a parameter issue. Skip the trial.
- **MCP server unavailable**: Fall back to CLI mode with the same commands.
- **All variants score 0**: Check `stt.capture_backend` in config (must be `gstreamer`). Also verify `audio.input_device` resolves to a live PipeWire source.
- **GStreamer unavailable**: The command will print `{"error": "GStreamer unavailable: ..."}`. Install `python3-gst-1.0` and `gstreamer1.0-plugins-bad` on the board, then run `uv sync --extra gstreamer --active`.
- **Variance too high** (scores swing > 30 between same-config trials): Speaking distance or timing is inconsistent. Ask the user to hold a steady position, wait for the tone, speak at a consistent volume.
- **MCP server restart needed**: If the server seems stale, it automatically reloads on reconnect. The `calibrate_reset()` tool clears session results without reloading the model.
