## 1. Seeded pink noise reproducibility

- [x] 1.1 Add `np.random.seed(42)` at the start of `_generate_pink_noise()` in `autogain.py`
- [x] 1.2 Add test in `tests/test_autogain.py` asserting identical output from two calls

## 2. Robust noise floor with median of 3 measurements

- [x] 2.1 Refactor `_measure_noise_floor()` to run 3 × 0.3s captures with 0.1s gaps
- [x] 2.2 Compute median RMS per channel across the 3 captures
- [x] 2.3 Update callers that use noise floor data
- [x] 2.4 Update existing noise floor tests; add test asserting transient immunity

## 3. Channel balance penalty in gain selection

- [x] 3.1 Compute channel imbalance ratio (dB) from `multi` array in `_analyze_capture()` or new helper
- [x] 3.2 Apply `weighted_snr *= 0.5` when imbalance > 6 dB in `_select_best_gain()`
- [x] 3.3 Add unit tests: balanced wins vs unbalanced with equal SNR, unbalanced still wins if SNR is high enough

## 4. Frequency-weighted SNR (mel-scale approximation)

- [x] 4.1 Add FFT-based band analysis function: low (0–300 Hz) weight 0.5, speech (300–3400 Hz) weight 2.0, high (3400+ Hz) weight 0.5
- [x] 4.2 Replace broadband SNR calculations in `run_autogain_auto()` with weighted SNR
- [x] 4.3 Update `_print_acoustic_summary()` to show weighted SNR columns
- [x] 4.4 Add tests: ensure speech-band noise produces higher weighted SNR than low-band noise

## 5. Multi-volume refinement pass

- [x] 5.1 Modify refinement loop in `run_autogain_auto()` to test fine gains at all 3 volumes ("lontano", "medio", "vicino")
- [x] 5.2 Compute weighted SNR for fine candidates using 5:2:1 (far:mid:near) ratio
- [x] 5.3 Add fallback to coarse winner if no fine candidate improves

## 6. STT validation pass after acoustic selection

- [x] 6.1 Add new function `_run_stt_validation(winner_gain, ...)` that synthesizes phrase via Piper, plays at "lontano", captures, transcribes, and scores
- [x] 6.2 Integrate into `run_autogain_auto()`: if STT score < 50%, test next-best gain; if all fail, keep acoustic winner
- [x] 6.3 Add tests: STT passes → keep gain, STT fails → try next, all fail → keep original

## 7. Less punitive confirmation fallback

- [x] 7.1 Add retry loop in the confirmation section of `run_autogain_auto()` (up to 3 attempts)
- [x] 7.2 Change fallback from hardcoded `gain=1.0` to the coarse (pre-refinement) winner
- [x] 7.3 Add tests: first attempt deviates, retry passes → keep winner; all fail → coarse winner

## 8. Test suite and final validation

- [x] 8.1 Run `uv run pytest tests/test_autogain.py -v` and fix any regressions
- [x] 8.2 Run `task lint` (ruff) and fix formatting issues
- [x] 8.3 Run `uv run pytest tests/` and verify no other tests broken
