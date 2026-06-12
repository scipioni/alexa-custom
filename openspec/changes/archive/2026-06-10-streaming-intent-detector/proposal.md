## Why

The two-stage STT pipeline forces a trade-off: `stage1.vad_silence_ms` must be long enough to bridge wake word + command in one breath (mode 2), but that same delay makes mode 1 feel sluggish. A streaming intent detector eliminates this tension by firing the moment a complete (wake + trigger) combination is stably recognized in the partial transcript — no silence wait needed.

## What Changes

- Stage-1 loop gains a partial-match early-exit path: on every Vosk partial result, check if the transcript stably matches any known `(wake phrase + trigger phrase)` combo
- A new `intent_map` is built at config load time from `alias_map × trigger phrases` (and their aliases)
- A stability window (configurable reads + ms) prevents single-frame Vosk partial flickers from firing
- Exact matching only on partials; fuzzy matching stays on the finalized fallback path
- New config keys under `recognition`: `partial_matching` (default `true`), `partial_stability_ms`, `partial_stability_reads`
- The existing VAD/endpoint fallback path is untouched — wake-only detection and LLM fallback continue to work as before

## Capabilities

### New Capabilities

- `streaming-intent-detection`: Continuously scans Vosk partial transcripts for complete (wake + trigger) intents, firing immediately when a match is stable — bypassing the VAD silence wait

### Modified Capabilities

- `multi-stage-stt`: Stage-1 gains a new early-exit path; config schema extended with partial-matching parameters

## Impact

- `alexa_custom/stt.py`: new `build_intent_map()`, `_match_full_intent()`, stability tracking in `_run_stt_loop()`
- `alexa_custom/stt_phonetics.py`: `build_intent_map()` lives here alongside `_build_alias_map()`
- `alexa_custom/config.py`: `RecognitionConfig` gains `partial_matching`, `partial_stability_ms`, `partial_stability_reads`
- `conf/config.yaml`: new optional keys under `recognition:`
- No new dependencies; no API or protocol changes
