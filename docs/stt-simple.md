# STT Pipeline — Speech-to-Text

## Architecture overview

A single **Vosk free-vocabulary** model runs continuously over the captured audio stream. There is no separate cheap-gate stage or stage-2 capture model — wake words and command phrases are matched directly against the single transcription stream.

```
┌─────────────────────────────────────────────────────────────────┐
│ mic audio                                                       │
│    │                                                            │
│    ▼                                                            │
│ capture backend (parec | gstreamer)                             │
│    │  raw s16le 16 kHz audio (mono after downmix)              │
│    ▼                                                            │
│ RMS gate → VAD → silence endpoint                               │
│    │  gated audio chunks                                       │
│    ▼                                                            │
│ Vosk decoder (always-on)                                        │
│    │  continuous transcript + endpoint events                   │
│    ▼                                                            │
│ Recognition loop                                                │
│    │  wake word match → open command window                     │
│    │  command match → dispatch (with inline-cmd shortcut)       │
│    │  direct trigger match (with_wake: false) → dispatch        │
│    │  no match → LLM fallback or error tone                     │
│    │  follow-up mode → re-open window without wake word         │
│    ▼                                                            │
│ Action dispatch → TTS / MQTT / Telegram / LiveKit / ...         │
└─────────────────────────────────────────────────────────────────┘
```

## Capture backends

### parec (default)

Uses `parec` (pulseaudio-utils) speaking the PulseAudio compat socket at `/run/user/1000/pulse/native`. Streams raw `s16le` 16 kHz stereo to stdout. No runtime dependency beyond `pulseaudio-utils`.

### gstreamer

Routes mic through a GStreamer pipeline with **webrtcdsp** (WebRTC Audio Processing Module) for noise suppression, AGC, high-pass filtering, and optional compressor before Vosk decodes. Configured under `audio.gstreamer.*`.

Activate with `stt.capture_backend: gstreamer`. Requires system packages:
- **Debian/Ubuntu**: `gstreamer1.0-plugins-bad` (webrtcdsp), `gstreamer1.0-pulseaudio` (pulsesrc), `python3-gst-1.0` (gi bindings), and optional `gstreamer1.0-pipewire` (pipewiresrc).
- **Arch Linux**: `gstreamer`, `gst-plugins-bad`, `gst-plugins-good`, `gst-plugins-base`, `gst-plugin-pipewire`, `python-gobject`.

Install with `task setup:gstreamer` (or `go-task setup:gstreamer` on Arch).

```yaml
stt:
  capture_backend: gstreamer

audio:
  gstreamer:
    source: pipewiresrc        # pulsesrc | pipewiresrc (confirmed on NewPie + PipeWire 1.4.2)
    noise_suppression: true
    noise_suppression_level: 2 # 0=mild 1=moderate 2=high 3=very-high
    agc: true
    agc_target_level_dbfs: -3  # calibration-verified optimal
    agc_compression_gain_db: 9 # calibration-verified optimal for normal distance
    high_pass_filter: true     # 80 Hz (removes USB power hum; essential for wake-word clarity)
    compressor: false
    profiles:
      normal:                  # calibration-verified on NewPie USB mic
        noise_suppression_level: 2
        agc_target_level_dbfs: -3
        agc_compression_gain_db: 9
        rms_threshold: 0.02
        vad_silence_ms: 900
      sensitive:               # calibration-verified for distant-mic use
        noise_suppression: false        # NS suppresses quiet distant speech as noise
        noise_suppression_level: 2      # (irrelevant when noise_suppression: false)
        agc_target_level_dbfs: -3
        agc_compression_gain_db: 70    # much higher gain for distant mic
        rms_threshold: 0.006            # lower to catch weaker signal
        vad_silence_ms: 1200
```

Each profile can override GStreamer parameters AND STT parameters (`rms_threshold`, `vad_silence_ms`). Switch at runtime via the `set_audio_profile` action type.

### GStreamer calibration

The `serena-stt --calibrate-gstreamer` mode lets you systematically tune the pipeline for your hardware and room. It speaks a phrase via TTS, plays a ready tone, captures your voice through the GStreamer pipeline, decodes with Vosk, and prints a JSON result:

```bash
# One-shot trial with default params
uv run --active serena-stt --calibrate-gstreamer --phrase "ehi serena volume alto"

# Override any GStreamer parameter for the trial
uv run --active serena-stt --calibrate-gstreamer --phrase "ehi serena volume alto" \
  --no-noise-suppression --agc-compression-gain-db 70 --rms-threshold 0.008
```

**Available override flags:**

| Flag | Default | Range |
|------|---------|-------|
| `--noise-suppression` / `--no-noise-suppression` | true | — |
| `--noise-suppression-level N` | 2 | 0–3 |
| `--agc` / `--no-agc` | true | — |
| `--agc-target-level-dbfs N` | -3 | negative int |
| `--agc-compression-gain-db N` | 9 | 0–90 |
| `--high-pass-filter` / `--no-high-pass-filter` | true | — |
| `--compressor` / `--no-compressor` | false | — |
| `--compressor-threshold F` | 0.1 | 0.0–1.0 |
| `--compressor-ratio F` | 3.0 | ≥1.0 |
| `--listen-seconds N` | 4.0 | float |
| `--rms-threshold F` | from config | float |

**JSON output fields:**

| Field | Meaning |
|-------|---------|
| `transcript` | What Vosk heard |
| `match_score` | Fuzzy similarity 0–100 |
| `speech_ratio` | Fraction of chunks above RMS threshold — proxy for signal strength |
| `rms_peak` | Peak RMS across the capture window |
| `captured_seconds` | Actual capture duration (< 3.0 = pipeline failure) |
| `gst_params` | Full parameter set used for this trial |

**MCP server (faster iteration):**

The `serena-calibrate-mcp` server keeps the Vosk model and TTS engine resident between trials, saving ~5 s per trial compared to the CLI. It is registered in `.claude/settings.json` and starts automatically in Claude Code sessions:

```
calibrate_init(phrase, listen_seconds?, rms_threshold?)   ← load once
calibrate_trial(noise_suppression?, agc_compression_gain_db?, …)  ← one trial
calibrate_summary()   ← ranked table + winning YAML
```

**Calibration findings (NewPie USB mic, Arduino Uno Q):**

*Normal profile (≤ 2 m from mic):*
- `noise_suppression_level: 2` is the sweet spot — levels 0, 1, 3 all score lower
- `agc_compression_gain_db: 9` — higher values amplify the noise floor
- HPF is essential — disabling it garbles the wake word
- Compressor off — enabling it reduces `speech_ratio` with no transcript benefit

*Sensitive profile (distant mic / reverberant room):*
- `noise_suppression: false` — NS treats quiet distant speech as noise and suppresses it
- `agc_compression_gain_db: 70` — higher gain is needed to reach Vosk's recognition threshold
- Wake word detection at distance remains limited by SNR; command words are more reliably captured than the "ehi serena" prefix

Run the `/calibrate-gstreamer` agent skill in Claude Code to redo the sweep automatically.

## Trigger matching

Every transcript passes through a two-phase matcher:

### Phase 1 — Word-glob patterns (definitive)

If a trigger defines `patterns`, these are tested first. A pattern match immediately selects that trigger — no scoring, no fallback.

Token syntax:
- `accend*` — word that *starts with* `accend` (matches accendi/accenda/accendere)
- `*` (standalone) — zero or more intervening words (greedy but ordered)
- `luci` — literal token matched **phonetically** via `italian_phonetic()` + similarity threshold

```yaml
triggers:
  - commands: ["accendi le luci"]
    patterns:
      - "accend* * luc*"    # accendi/accenda… + any words + luci/luce
    actions:
      - type: mqtt_publish
        topic: home/light/set
        payload: "ON"
```

| Transcript | Result |
|---|---|
| `accendi le luci` | ✅ |
| `accendimi le luci del salotto` | ✅ |
| `spegni le luci` | ❌ no word starts with `accend` |
| `luci accendi` | ❌ wrong order |

**Designed for Italian verb inflection**: one pattern (`accend*`) covers all forms of the same verb, eliminating the need for dozens of aliases.

### Phase 2 — Fuzzy phonetic scoring (fallback)

When no pattern matches, each trigger is scored against the transcript:

1. Both strings are normalized via `italian_phonetic()` — handles geminate consonants, `gli→li`, `gn→n`, `ch→k`, `qu→k`, `sci→si`, etc.
2. Similarity is computed using the configured `matching_algorithm`:
   - **`token_sort_ratio`** (default) — order-tolerant, length-aware. Best general-purpose. A single word ("sono") cannot match a longer phrase ("che ore sono").
   - **`token_set_ratio`** — token-subset scoring. Prone to false fires when transcript is a subset of the phrase.
   - **`levenshtein`** — character-level edit distance. Strict, good for short phrases.
   - **`ratio`** — character-level ratio. Used internally for direct triggers.
3. Optional `min_word_overlap` guard: fraction of content words that must appear verbatim before scoring runs. `0.0` (default) = off.
4. Trigger with the highest score above `matching_threshold` (**75.0**) wins.

## Wake word detection

Wake words are a flat list of strings in `wake_words:`:

```yaml
wake_words:
  - "ehi serena"
  - "ascolta assistente"
```

Extra wake phrases can be added from `conf/actions/*.yaml` files via a `wake_words:` key at the top of each action file.

When a wake word is detected:
1. The configured `wake_tone` plays (default: `wake`).
2. A **command window** opens for `recognition.wake_window` seconds (default: 8.0).
3. Any transcript during the window is checked against trigger commands.

### Direct triggers (with_wake: false)

Triggers with `with_wake: false` fire **without** any wake word:

```yaml
triggers:
  - commands: ["chiama Stefano"]
    with_wake: false
    actions:
      - type: livekit_join
```

Because there is no wake word gating, direct triggers use stricter matching:
- Algorithm: `ratio` (character-level), not `matching_algorithm`
- Full word overlap enforced (`min_word_overlap` = 1.0 internally)
- Word-count gate: transcript must have at least as many words as the phrase
- Threshold: must still clear `matching_threshold`

### One-breath inline command

If the user speaks wake word + command in one utterance (e.g. "ehi serena che ore sono"), the trailing text is extracted and dispatched directly, skipping the command window. This eliminates one round-trip.

### Sleeping mode

The `stop_listening` action puts STT to sleep — all wake words are ignored. The `start_listening` action wakes it back up. Configure wake-up phrases as `with_wake: false` triggers:

```yaml
triggers:
  - commands: ["svegliati adesso"]
    with_wake: false
    actions:
      - type: start_listening
```

## Command window and follow-up

After a wake word, a **command window** opens. If the transcript matches a trigger command, the action dispatches. If no match, an error tone plays (or LLM fallback if enabled).

### Follow-up conversation mode

When `recognition.follow_up: true`, after a matched command the window re-opens without requiring the wake word:

```yaml
recognition:
  follow_up: true
  follow_up_timeout: 4.0     # silence before window closes
  follow_up_max_turns: 5     # max consecutive follow-up turns
  follow_up_tone: info       # chime when follow-up opens
```

Per-trigger override:

```yaml
triggers:
  - commands: ["buonanotte"]
    follow_up: false         # force-close even when follow_up is globally on
    actions:
      - type: say
        text: "Buonanotte!"
```

## Ask action — reply matching

The `ask` action type uses a constrained listen window with reply triggers:

```yaml
actions:
  - type: ask
    text: "Vuoi chiamare Stefano?"
    lang: "it-IT"
    timeout: 5.0
    on_reply:
      - commands: ["si", "ok", "certo"]
        actions:
          - type: say
            text: "Sto chiamando Stefano"
    on_else:
      - type: say
        text: "Non ho capito"
```

Reply matching uses `reply_matching_algorithm` (**levenshtein**) and `reply_matching_threshold` (**80.0**), configurable separately from command matching.

## LLM fallback

When `llm.fallback_on_no_match: true`, unmatched commands are routed to the configured LLM (ollama or openai) instead of playing the error tone.

## Vosk backend benchmark

| Metric (live mic, always-on) | vosk | sherpa-onnx (removed) |
|---|---|---|
| Model load time | **2.8 s** | 40 s |
| CPU (continuous decode) | **66–70 %** | 103 % |
| RTF p95 (decode/audio) | 0.39–0.75 | 0.31 |
| Endpoint latency p95 | **1059 ms** | 1806 ms |
| Live transcripts | **clean, full** | **fragmented** |
| Idle false fires | 0 | 0 |

`vosk` is the only supported backend. sherpa-onnx was removed due to 40 s load time, fragmented utterances, and high CPU usage.

### Tuning notes

- `vad_silence_ms` **900** — 500 ms chops utterances; 900 ms gives clean transcripts. Perceived latency ≈ vad_silence_ms + ~130 ms decode.
- Open-vocabulary wobble (e.g. `figure sono` for "che ore sono") is expected and absorbed by `matching_threshold`.
- Re-run `scripts/bench_stt.py` after backend or loop changes to catch regressions.

## VAD gating

The system gates recognized audio through:

1. **RMS threshold** (`stt.rms_threshold`: **0.02**) — minimum energy level for speech detection.
2. **Adaptive RMS** (`stt.adaptive_rms`: **true**) — dynamically adjusts threshold based on noise floor (`adaptive_rms_margin`: **0.01**).
3. **Min speech** (`stt.min_speech_ms`: **200**) — minimum sustained speech before silence timer starts.
4. **Post-dispatch cooldown** (`recognition.post_dispatch_cooldown_ms`: **800**) — silence listening after dispatch to prevent echo re-trigger.
5. **Min command words** (`recognition.min_cmd_words`: **1**) — minimum word count in command before matching runs.

## Configuration reference

```yaml
stt:
  backend: vosk                     # must be vosk (sherpa-onnx removed)
  model_path: null                  # override default model path
  num_threads: 2                    # ONNX threads (vosk ignores this)
  vad_silence_ms: 900               # ms of silence before endpoint
  rms_threshold: 0.02               # minimum RMS energy for speech
  adaptive_rms: true                # dynamic threshold adjustment
  adaptive_rms_margin: 0.01
  min_speech_ms: 200                # min sustained speech before VAD starts
  wake_match_threshold: 0.5         # fraction of wake-phrase tokens required
  mono_capture: false               # force parec mono capture
  capture_backend: parec            # parec (default) | gstreamer

recognition:
  wake_window: 8.0                  # command window duration (seconds)
  wake_tone: wake                   # tone name on wake
  call_tone: true                   # tones on call connect/disconnect
  matching_algorithm: token_sort_ratio
  matching_threshold: 75.0
  min_word_overlap: 0.0
  reply_matching_algorithm: levenshtein
  reply_matching_threshold: 80.0
  follow_up: false
  follow_up_timeout: 4.0
  follow_up_max_turns: 5
  follow_up_tone: info
  post_dispatch_cooldown_ms: 800
  min_cmd_words: 1
  dispatch_timeout: 90.0
```
