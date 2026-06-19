# STT Pipeline and Trigger Matching

> **Full reference**: see [`docs/stt-simple.md`](stt-simple.md) for the complete pipeline description, benchmark data, and all configuration keys.

alexa-custom runs a **single-model always-on** speech pipeline. A single Vosk free-vocabulary model transcribes audio continuously; wake words and command triggers are matched directly against this stream. There is no two-stage pipeline — no separate cheap-gate model, no stage-2 capture model.

## Pipeline overview

```
mic audio → capture backend (parec | gstreamer) → RMS/VAD gating → Vosk decoder → recognition loop → action dispatch
```

## Capture backends

- **`parec`** (default): uses pulseaudio-utils, raw s16le 16 kHz stereo to stdout.
- **`gstreamer`**: routes through GStreamer with webrtcdsp (noise suppression, AGC, high-pass filter, compressor). Activate with `stt.capture_backend: gstreamer`. Supports named audio profiles switchable at runtime via `set_audio_profile`.

## Trigger matching

Two phases:

1. **Word-glob patterns** (definitive): pattern tokens like `accend*` (word prefix), `*` (gap), `luci` (phonetic literal) are matched in order. A hit immediately selects the trigger. Designed for Italian verb inflection — one pattern covers all forms of a verb.

2. **Fuzzy phonetic scoring** (fallback): normalizes via `italian_phonetic()` (handles `gli→li`, `gn→n`, `ch→k`, `qu→k`, geminate consonants), then scores with the configured `matching_algorithm` (`token_sort_ratio` ∎, `token_set_ratio`, `levenshtein`, `ratio`).

## Direct triggers (`with_wake: false`)

Fire without a wake word. Uses stricter matching: `ratio` algorithm + full word overlap + word-count gate. Configure:

```yaml
triggers:
  - commands: ["chiama Stefano"]
    with_wake: false
    actions:
      - type: livekit_join
```

## One-breath inline command

Wake word + command in one utterance ("ehi serena che ore sono") dispatches directly, skipping the command window.

## Follow-up conversation mode

Enabled with `recognition.follow_up: true`. After a matched command, the listening window re-opens without re-waking. Configurable timeout, max turns, and per-trigger override.

## Sleeping mode

`stop_listening` → STT sleeps; `start_listening` → STT wakes. Configure wake-up phrases as `with_wake: false` triggers with `type: start_listening`.

## LLM fallback

`llm.fallback_on_no_match: true` routes unmatched commands to the configured LLM (ollama or openai) instead of playing the error tone.

## Ask action reply matching

Uses `reply_matching_algorithm` (**levenshtein**) and `reply_matching_threshold` (**80.0**) separately from command matching. Constrained grammar improves accuracy for yes/no replies.

## Benchmark

Vosk is the only supported backend. sherpa-onnx was removed: 40 s load time (vs Vosk 2.8 s), 103 % CPU (vs 66–70 %), fragmented utterances. See `docs/stt-simple.md` for full benchmark table.

## Key tuning knobs

| Symptom | Fix |
|---|---|
| Utterances chopped | Raise `stt.vad_silence_ms` (e.g. 900–1200 ms) |
| Pipeline doesn't end after command | Lower `stt.vad_silence_ms` |
| Pattern too permissive | Add stronger anchor token; avoid bare single-token patterns |
| Direct trigger won't fire | Add mis-transcribed form as an `alias` |
