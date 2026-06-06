# Capability: Piper Streaming Playback

## Purpose
Stream Piper TTS audio sentence-by-sentence to the PipeWire default sink via `paplay`, reducing first-word latency for multi-sentence responses.

## Requirements

### Requirement: Piper streams audio sentence-by-sentence via paplay
`PiperTTS.say()` SHALL open a single `paplay --raw` subprocess at the start of synthesis and write each `AudioChunk` from `PiperVoice.synthesize()` to its stdin as soon as the chunk is available, rather than collecting all chunks before playback begins.

#### Scenario: First sentence plays before second is synthesised
- **WHEN** `PiperTTS.say()` is called with a two-sentence text
- **THEN** audio for the first sentence begins playing as soon as the first chunk is synthesised, before the second chunk is ready

#### Scenario: Single-sentence text plays correctly
- **WHEN** `PiperTTS.say()` is called with a single sentence
- **THEN** audio plays correctly via `paplay`, with no regression vs. the previous path

### Requirement: Preroll silence delivered as raw bytes
`PiperTTS.say()` SHALL write `preroll_ms` milliseconds of s16le zero bytes to `paplay` stdin before the first audio chunk when `preroll_ms > 0`.

#### Scenario: Preroll silence precedes speech
- **WHEN** `PiperTTS` is initialised with `preroll_ms=400`
- **THEN** 400 ms of silence plays before the first word of synthesised speech

### Requirement: Playback gating preserved during streaming
The `_playback_active` flag and `_audio_lock` SHALL be held for the entire duration of the `paplay` subprocess, from the moment it is opened until it exits.

#### Scenario: STT remains gated throughout multi-sentence playback
- **WHEN** `PiperTTS.say()` is streaming a multi-sentence response
- **THEN** `is_playback_active()` returns `True` for the full duration, including the gap between sentence chunks

### Requirement: paplay absence falls back gracefully
If `paplay` is not found on the system, `PiperTTS.say()` SHALL fall back to collecting all chunks and writing a WAV file played via `aplay -D pipewire`.

#### Scenario: Fallback when paplay absent
- **WHEN** `paplay` is not available on the system
- **THEN** `PiperTTS.say()` produces audio via the WAV-file fallback without raising an exception
