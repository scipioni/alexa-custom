## Context

The `run_autogain_auto()` function in `alexa_custom/autogain.py` performs automatic microphone gain calibration by:
1. Playing pink noise at 3 volume levels (far/medium/near: 6%, 30%, 80%)
2. Capturing the loopback signal via `parec`/`pw-record`
3. Measuring noise floor, SNR, headroom, and clipping per gain
4. Selecting the best gain via `_select_best_gain()` (filters on clipping + headroom + far SNR)
5. Refining with 0.1-step sweep around winner on "lontano" only
6. Confirming with a repeat measurement at "medio"

Current limitations: channel balance ignored, refinement only at one volume, confirmation fallback is gain=1.0, no STT validation, noise floor measured once (fragile), pink noise unseeded (non-reproducible), SNR is broadband.

## Goals / Non-Goals

**Goals:**
- Improve gain selection accuracy by 7 targeted algorithmic improvements
- Keep the calibration fully automatic (no human intervention)
- Maintain backward compatibility — existing config values remain valid
- Add STT validation as a final verification step without making it the primary metric

**Non-Goals:**
- Changing the interactive calibration path (`run_autogain_interactive`, `main()`)
- Adding new CLI flags or configuration options (all improvements are internal algorithm changes)
- Replacing the pink noise approach entirely
- Supporting multi-room or multi-device calibration

## Decisions

### 1. Channel balance penalty instead of hard filter
Channel imbalance can indicate a directional noise source or a hardware issue. Instead of excluding unbalanced gains (which could leave no candidates), apply a penalty factor of 0.5× to `weighted_snr` when imbalance exceeds 6 dB. This lets the gain still win if its SNR is high enough, but gives balanced gains an advantage.

### 2. Multi-volume refinement at all 3 levels
Instead of refining only on "lontano", test fine-grained candidates at "lontano", "medio", and "vicino". Weigh them with the same 5:2:1 ratio used in the coarse pass. This adds ~24 captures (3 volumes × 8 fine gains) instead of ~8 — still completes in under 10 seconds because each capture is 1 second.

### 3. Retry loop for confirmation, fallback to coarse winner
If confirmation deviates >20%, retry up to 2 more times (3 total). If all fail, use the coarse winner instead of hardcoded 1.0. Rationale: the coarse winner already passed all selection criteria; a transient disturbance shouldn't discard it.

### 4. STT validation as a second pass
After acoustic selection, synthesize `_SPEECH_TEST_PHRASE` via Piper, play at "lontano" volume (worst-case SNR), capture, transcribe, and score with `get_similarity_score("token_set_ratio")`. If score < 50%, reject and test the next-best gain. If all candidates fail STT, keep the acoustic winner (STT as guard, not gate).

### 5. Median of 3 noise floor measurements
`_measure_noise_floor()` runs 3 × 0.3s captures with 0.1s gaps, computes RMS per channel for each, then takes the median. Immunity against transient noise (door slam, cough) without adding significant time.

### 6. `np.random.seed(42)` in `_generate_pink_noise`
Makes pink noise deterministic across runs. Essential for debugging and comparison testing.

### 7. Mel-scale frequency weighting
Apply a simple 3-band weighting to the SNR calculation: 0–300 Hz (low) weight 0.5, 300–3400 Hz (speech band) weight 2.0, 3400+ Hz (high) weight 0.5. Implemented as FFT → bin assignment → weighted RMS. Avoids external DSP dependencies.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| [Multi-volume refinement] 24 extra captures ≈ 8s more runtime | Already < 30s total; acceptable for a setup operation |
| [STT validation] Piper synthesis + transcription depends on model availability | Falls back to acoustic winner gracefully |
| [Frequency-weighted SNR] FFT adds ~2ms per capture on the aarch64 board | Precompute FFT plan, reuse buffer |
| [All changes] Test suite needs significant updates | Run targeted pytest on `tests/test_autogain.py` only |
| [Channel balance penalty] Might still select unbalanced gain in edge cases | Acceptable — penalty merely discourages, doesn't forbid |
