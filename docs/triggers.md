# STT Recognition Modes

alexa-custom supports two speech interaction patterns in two-stage mode.

---

## Mode 1 — wake word → beep → command

The user speaks the wake word, pauses, waits for the beep, then speaks the command as a separate utterance.

```
[user: "arduino"]  →  stage-1 fires  →  beep plays  →  [user: "chiama stefano"]  →  stage-2 captures
```

### Flow

1. **Stage-1** runs continuously. Vosk (free-vocabulary) accumulates audio chunks.
   - The software VAD fires when `stage1.vad_silence_ms` of silence is detected after
     at least `stage1.min_speech_ms` of speech.
   - Alternatively, Vosk's internal endpoint detector fires first — whichever comes first.
2. `_extract_wake_command()` checks if the transcript matches a wake word. On match, `inline_cmd` is empty.
3. The wake beep plays (`pw-play`), blocking until done.
4. **Stage-2** (`capture_transcript`) starts:
   - `_drain_pipe()` flushes all audio that accumulated in the pipe during the beep.
   - An additional `flush_ms` (hardcoded 300 ms) of fresh audio is discarded to let
     speaker echo and reverberation decay.
   - Vosk listens until `stt.vad_silence_ms` of silence or `command_timeout` expires.
   - The final transcript is matched against triggers.

### Tuning

| Parameter | Location | Effect |
|-----------|----------|--------|
| `stage1.vad_silence_ms` | `conf/config.yaml` `stt.stage1` | How long after the wake word before stage-1 fires. Lower = snappier; the user can start speaking sooner. |
| `stage1.min_speech_ms` | `conf/config.yaml` `stt.stage1` | Minimum speech before the VAD timer starts. Prevents noise from triggering early finalization. |
| `stt.vad_silence_ms` | `conf/config.yaml` `stt` | Silence that ends the command window in stage-2. Lower = snappier end detection; raise if commands get cut off mid-sentence. |
| `recognition.command_timeout` | `conf/config.yaml` `recognition` | Hard deadline for stage-2 capture in seconds. |
| `flush_ms` | hardcoded 300 ms in `stt.py:_wake_detected` | Audio discarded after the beep to absorb echo. Reducing this can help if the user speaks immediately after the beep, but risks picking up speaker echo. |

---

## Mode 2 — one breath (wake word + command, no pause)

The user speaks wake word and command in a single continuous utterance without waiting for the beep.

```
[user: "arduino chiama stefano"]  →  stage-1 fires  →  inline_cmd extracted  →  beep plays  →  stage-2 skipped
```

### Flow

1. **Stage-1** accumulates audio as in mode 1.
   - The VAD window (`stage1.vad_silence_ms`) must remain open long enough to capture
     the entire phrase including the command words.
2. `_extract_wake_command()` strips the wake word from the transcript and returns the
   remainder as `inline_cmd` (e.g. `"chiama stefano"`).
3. `_wake_detected` is called with `pre_transcript=inline_cmd` — it **skips**
   `capture_transcript` entirely and goes straight to trigger matching.
4. The beep plays after the match, so the user hears confirmation but does not need
   to speak again.

### Why it can fail

If the user makes any pause between the wake word and the command that exceeds
`stage1.vad_silence_ms`, stage-1 fires on the wake word alone (`inline_cmd=""`).
The daemon then plays the beep and calls `capture_transcript`, which calls
`_drain_pipe()` — **throwing away any command words already spoken**. The user must
repeat the command after the beep (falling back to mode 1).

The default `stage1.vad_silence_ms` is 900 ms (as configured in `conf/config.yaml`),
which bridges most natural micro-pauses after the wake word.

### Tuning

| Parameter | Location | Effect |
|-----------|----------|--------|
| `stage1.vad_silence_ms` | `conf/config.yaml` `stt.stage1` | **Primary knob for mode 2.** Must be wider than the longest pause the user makes between wake word and command. Raise if mode 2 keeps falling back to mode 1; lower if mode 1 latency is too high. |
| `stage1.min_speech_ms` | `conf/config.yaml` `stt.stage1` | Minimum speech before the VAD timer starts. Prevents the VAD from triggering on a brief syllable. |

---

## Comparison

| | Mode 1 | Mode 2 |
|-|--------|--------|
| Speaking pattern | Wake word → pause → beep → command | Wake word + command in one breath |
| Beep timing | Before command | After command |
| Stage-2 capture | Yes — full `capture_transcript` | No — `inline_cmd` from stage-1 |
| Sensitivity to `stage1.vad_silence_ms` | Low (Vosk endpoint usually fires first) | High — must exceed pause between wake word and command |
| Sensitivity to `stt.vad_silence_ms` | High — controls command end detection | None |
| Risk of losing command audio | None | Yes, if pause > `stage1.vad_silence_ms` |

---

## Current configuration

```yaml
stt:
  vad_silence_ms: 500      # stage-2 command-end silence (mode 1)

  stage1:
    backend: vosk
    vad_silence_ms: 900    # bridges wake word + command pause (mode 2)
    min_speech_ms: 300
```

`recognition.command_timeout: 3.0` (in `conf/config.yaml` under `recognition`).
