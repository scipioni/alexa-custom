## Context

`PiperTTS.say()` currently collects all synthesis chunks from `piper.PiperVoice.synthesize()` into a list, concatenates them into a single numpy array, writes a temporary WAV file, and plays it via `pw-play file.wav`. This means the user hears nothing until the entire utterance is synthesized — for a two-sentence response, that's the synthesis time of both sentences before any audio begins.

`paplay --raw` is already proven on this board: `client.py` uses it to stream LiveKit remote audio with `stdin=PIPE`. `pw-play --raw` (stdin) does not work reliably on PipeWire 1.4.2 on this board (noted in CLAUDE.md). `paplay` speaks the PulseAudio compat socket and is the correct streaming sink.

`piper.PiperVoice.synthesize()` yields one `AudioChunk` per sentence. For an N-sentence utterance, chunk 0 is ready while chunk 1 is still being synthesized — streaming pipelines these naturally.

## Goals / Non-Goals

**Goals:**
- Start audio output after the first sentence is synthesized, not after all sentences.
- Preserve `_audio_lock` and `_playback_active` semantics — STT gating continues to work as before.
- Preserve preroll silence behaviour.
- No new dependencies.

**Non-Goals:**
- Sub-sentence streaming (piper's Python API yields per-sentence; finer granularity would require the piper binary with `--output-raw` and per-invocation model loading overhead).
- Changing `PicoTTS` — unaffected.
- Changing the fallback `aplay` path used for WAV files elsewhere in `audio.py`.

## Decisions

### D1: `paplay --raw` over `pw-play --raw` for streaming

`pw-play --raw -` exits 0 but produces no audio on this board's PipeWire 1.4.2. `paplay --raw` works via the PulseAudio compat socket — the same socket `parec` uses for capture. Already validated in `client.py`. No alternative viable.

### D2: Single long-lived `paplay` process per `say()` call

One paplay process is opened at the start of `say()`, chunks are written to its stdin as they arrive, then stdin is closed and the process is joined. This avoids the gap between sentences that would occur with one-paplay-per-chunk.

Alternative considered: one `_play_array` call per chunk. Rejected: each chunk starts a new `pw-play` invocation with a gap between them.

### D3: Full streaming always — no single-sentence fallback

Piper on this board runs faster than real-time. Underrun risk is low. A conditional path adds complexity with little safety benefit. If paplay fails for any reason the exception is caught and logged, matching current behaviour.

### D4: Preroll as zero bytes written before the first chunk

Currently preroll silence is a numpy array prepended to the audio. With streaming, the equivalent is writing `preroll_ms * samplerate / 1000 * 2` zero bytes (s16le) to paplay stdin before the first chunk. Identical audible effect, zero extra memory.

### D5: `_audio_lock` held for the full streaming duration

`paplay` is opened inside `with _audio_lock`, same as `_play_array`. This blocks concurrent playback and keeps the STT gating window correct.

## Risks / Trade-offs

[Underrun on CPU spike] → Piper is faster than real-time on this board; acceptable risk. If heard in practice, a small pre-buffer (collect first chunk before opening paplay) can be added without changing the interface.

[paplay not found] → `shutil.which("paplay")` checked at `say()` time; falls back to writing a WAV and calling `aplay -D pipewire`, same as the existing `_play_array` fallback chain.

[samplerate discovery] → `chunk.sample_rate` is read from the first chunk, same as today. No change in risk.
