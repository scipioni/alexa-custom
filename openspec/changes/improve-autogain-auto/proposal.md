## Why

The current automatic microphone gain calibration (`run_autogain_auto`) uses pink noise + acoustic analysis but never validates against real STT performance. Several metrics are computed but ignored in the final selection (`channel_balanced`), the confirmation fallback is too aggressive (straight to gain=1.0), and the noise floor measurement is fragile against transient noise. These gaps mean the chosen gain may work acoustically but produce poor transcription quality.

## What Changes

1. **Use `channel_balanced` in gain selection** — exclude or penalize gains with >6dB imbalance between channels
2. **Multi-volume refinement** — test fine-grained candidates at all 3 playback volumes, not just "lontano"
3. **Less punitive confirmation** — retry up to 3 times before fallback; use coarse winner as fallback instead of hardcoded 1.0
4. **STT validation pass** — after acoustic selection, play a Piper-synthesized phrase, transcribe it, score with `get_similarity_score`, and fall back to runner-up if score < 50%
5. **Robust noise floor** — take median of 3 measurements instead of a single 0.5s capture
6. **Seeded pink noise** — `np.random.seed(42)` for reproducible results between runs
7. **Frequency-weighted SNR** — apply mel-scale weighting (300–3400 Hz emphasis) instead of broadband SNR

## Capabilities

### New Capabilities
- `auto-gain-calibration`: Automatic microphone gain calibration using pink noise playback, acoustic loopback analysis, and post-selection STT validation. Runs without human intervention.

### Modified Capabilities
- `input-gain-calibration`: The interactive action-based calibration spec is unchanged. The new `auto-gain-calibration` capability adds a separate code path that does not affect the existing interactive flow.

## Impact

- **`alexa_custom/autogain.py`**: Major changes to `run_autogain_auto`, `_select_best_gain`, `_measure_noise_floor`, `_generate_pink_noise`, `_compute_weighted_snr`, plus new `_run_stt_validation` function
- **`alexa_custom/stt_backends.py`**: No changes needed (STT validation reuses existing pipeline)
- **`alexa_custom/audio_ops.py`**: No changes needed
- **`alexa_custom/audio_hw.py`**: No changes needed
- **Tests**: `tests/test_autogain.py` — update existing tests, add tests for new selection logic, multi-volume refinement, STT validation pass, robust noise floor, seeded reproducibility
