## Context

The current `alexa-mic-test` (`run_autogain_auto()` in `autogain.py:624`) uses pink noise as a test signal and scores gains by acoustic metrics (SNR, headroom, clipping). It has a mature sweep/refine/confirm structure and robust playback/capture via `pw-play` + `parec`.

The interactive `alexa-autogain` (`run_autogain_interactive()` at line 338) *does* score by real STT transcription, but requires a human speaker and TTS prompts — not suitable for headless operation.

This design bridges the gap: fully automatic, but scores by actual STT accuracy using the configured backend.

## Goals / Non-Goals

**Goals:**
- New `alexa-mic-calibrate` CLI command: plays pre-recorded speech, captures loopback, transcribes with the actual STT backend, scores by similarity, selects+p persists best gain
- Share sweep/refinement/confirmation scaffolding with the existing pink-noise calibrator
- Ship a test phrase WAV (`models/test_phrase.wav`) — pre-recorded human Italian voice saying "ascolta assistente chiama aiuto"
- Support all STT backends (Vosk, sherpa-onnx, whisper-cpp, nemo-offline) transparently

**Non-Goals:**
- Real-time adaptive gain during daemon operation (future option 5)
- Multiple test phrases or phonetically-balanced corpus (single phrase is sufficient for relative gain ranking)
- Replacing `alexa-mic-test` — both coexist; pink noise remains useful for acoustic debugging

## Decisions

### Decision 1: Pre-recorded speech WAV vs TTS-generated
**Chosen: Pre-recorded human voice WAV shipped in repo.**

Alternatives considered:
- **TTS-generated**: No binary asset needed, but Piper's voice sounds different from real speech. The STT model was trained on human speech, so TTS loopback scores may not rank gains correctly relative to real-world use.
- **User-records at setup**: Gold standard for voice match, but adds a setup step and requires the user to speak a phrase — defeats the "fully automatic" goal.

The pre-recorded WAV is a one-time ~3 second 16-bit 16kHz mono file. It's reproducible and guarantees the same test signal across calibrations.

### Decision 2: Scoring function
**Chosen: `get_similarity_score(expected, actual, "token_set_ratio")` + clipping penalty.**

- `token_set_ratio` from rapidfuzz (already used by the interactive calibrator) is forgiving of word reordering and partial matches — good for STT evaluation where the model may drop/insert articles
- Clipping penalty mirrors the existing logic: >5% clipped frames → score = 0; >1% → score *= 0.5

### Decision 3: Shared sweep infrastructure
**Chosen: Factor sweep loop into a generator that yields `(gain, captured_audio_dict)` — consumer decides scoring.**

Current `run_autogain_auto()` has three intertwined concerns:
1. Sweep orchestration (gain list, distance volumes, refinement, confirmation)
2. Capture/playback mechanics
3. Acoustic analysis + scoring

We extract (1) into a `_sweep_gains()` generator and (2) into `_play_and_capture()` helpers. The pink-noise analyzer and the new model-aware scorer each implement a thin scoring callback passed to the sweep orchestrator.

```
┌──────────────────────────────────────────────────┐
│               _sweep_gains()                      │
│                                                   │
│  TEST_GAINS ──▶ coarse(gain, medio) ──▶ top2     │
│  top2 ──▶ selective(near, far)                    │
│  ──▶ refine(winner, lontano)                      │
│  ──▶ confirm(winner, medio)                       │
│                                                   │
│  Callback: score_fn(gain, captured_audio)         │
│     ↑ pink-noise scorer   ↑ model-aware scorer    │
└──────────────────────────────────────────────────┘
```

### Decision 4: Output volume scaling for distance simulation
**Chosen: Reuse existing `_AUTO_PLAY_VOLUMES` and `_scale_wav_to_playback_volume()`.**

The same three simulated distances (lontano 0.06, medio 0.30, vicino 0.80) and weights (5, 2, 1) apply. The test speech WAV is scaled to each volume level before playback.

### Decision 5: STT backend lifecycle
**Chosen: Load the STT backend once at the start of calibration, reuse across all gain tests.**

Loading a Vosk/sherpa-onnx model is expensive (~1-3s). We load it once via `get_stt_backend(config.stt.stage2)`, call `reset()` between tests, and `finalize()` at the end of each capture.

## Flow

```
alexa-mic-calibrate
│
├─ 1. Load config, resolve capture source
├─ 2. Load STT backend (stage2)
├─ 3. Load test_phrase.wav → scale to 3 volumes
│
├─ 4. Sweep gains ── for each gain:
│     ├─ set_input_gain(gain)
│     ├─ play scaled WAV + capture simultaneously
│     ├─ transcribe captured audio via STT backend
│     ├─ score = similarity(test_phrase, transcription)
│     └─ apply clipping penalty
│
├─ 5. Refinement sweep around winner
├─ 6. Confirmation pass
├─ 7. Write winner to config.yaml
└─ 8. Print summary table
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **Speaker plays test audio → mic captures it → feedback loop if gain too high** | Playback happens at low volumes (0.06–0.80); capture runs synchronously after playback starts; the physical loopback is acoustic (speaker → room → mic), not electrical, so no feedback |
| **Room noise corrupts transcription scoring** | Same as existing pink-noise calibrator — noise floor is measured before each gain test; if SNR is too low, the gain is penalized indirectly (bad transcription → low score) |
| **STT backend not compatible with playback loopback audio (TTS artifacts)** | A real human voice WAV avoids TTS artifacts. If the STT backend still struggles, `token_set_ratio` is forgiving enough to produce meaningful relative scores |
| **Calibration takes ~45s** | Same duration as pink-noise calibrator. Acceptable for a setup-time operation. Could be shortened by testing fewer gains, but the current 6-gain sweep is well-established |
