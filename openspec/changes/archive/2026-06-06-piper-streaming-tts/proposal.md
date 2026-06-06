## Why

`PiperTTS.say()` currently collects all synthesis chunks before starting playback, so the user hears nothing until the entire utterance is synthesized. Streaming each sentence chunk to `paplay` as it arrives cuts first-audio latency to the time needed to synthesize one sentence.

## What Changes

- `PiperTTS.say()` replaces the collect-all-then-play approach with a single `paplay --raw` subprocess; each synthesis chunk is written to its stdin as it arrives.
- Preroll silence is written as zero bytes before the first chunk instead of prepended as a numpy array.
- `_play_array` (WAV file path) is no longer used by `PiperTTS`.

## Capabilities

### New Capabilities

- `piper-streaming-playback`: Piper TTS synthesises and streams audio sentence-by-sentence to `paplay` stdin, reducing first-audio latency for multi-sentence responses.

### Modified Capabilities

- `text-to-speech`: The TTS playback path for the Piper backend changes from WAV file → `pw-play` to raw PCM stream → `paplay`.

## Impact

- `alexa_custom/tts.py` — `PiperTTS.say()` rewritten; no new public API.
- `alexa_custom/audio.py` — no changes needed; `_audio_lock` and `_playback_active` are managed from `tts.py` via the new path.
- No new dependencies: `paplay` is already available and used in `client.py`.
- `PicoTTS` is unaffected.
