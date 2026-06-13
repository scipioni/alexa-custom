## 1. Test phrase WAV

- [x] 1.1 Record a 16-bit 16kHz mono WAV of a human Italian voice saying "ascolta assistente chiama aiuto" at `models/test_phrase.wav`
- [x] 1.2 Verify the WAV is valid and loadable (check sample rate, bit depth, channels, duration)

## 2. Shared helpers (extracted for reuse by both paths)

- [x] 2.1 Extract `_compute_fine_gains()` — pure function to compute refinement gain list
- [x] 2.2 Extract `_weighted_score()` — weighted average across distance labels
- [x] 2.3 Extract `_LABEL_TO_DIST` / `_DIST_TO_LABEL` — label↔distance name mapping constants
- [x] 2.4 Implement sweep + refine + confirm logic inside each path (pink-noise path unchanged, model-aware path uses same pattern)
- [x] 2.5 Keep `run_autogain_auto()` intact (no refactoring needed — pink-noise path verified via `alexa-mic-test`)

## 3. Implement model-aware scoring

- [x] 3.1 Implement `_score_transcription(expected_phrase, captured_audio_multi, stt_backend, channels) → float` that:
  - Downmixes to mono if stereo
  - Feeds audio through the STT backend in chunks
  - Calls `finalize()` and `get_similarity_score(expected, actual, "token_set_ratio")`
  - Applies clipping penalty (>5% → 0, >1% → ×0.5)
- [x] 3.2 Implement `_init_speech_test_wavs() → dict[label → wav_path]` that loads the test phrase WAV and scales to three volume levels

## 4. Implement model-aware calibrator

- [x] 4.1 Implement `run_autogain_model_aware(actions_config, dry_run=False) → float` that:
  - Loads config, resolves capture source
  - Loads the STT backend from `config.stt.stage2`
  - Generates scaled speech WAVs via `_init_speech_test_wavs()`
  - Phase 1: coarse sweep — all TEST_GAINS at all 3 volume levels
  - Phase 2: selective — top 2 gains at near + far distances
  - Phase 3: refinement sweep around winner at lontano volume
  - Phase 4: confirmation with retry/fallback
  - Saves winner to config (unless dry-run)
  - Prints summary table via `_print_model_aware_summary()`

## 5. CLI entry point

- [x] 5.1 Add `main_calibrate()` function in `autogain.py` with `--dry-run` flag
- [x] 5.2 Add `alexa-mic-calibrate = "alexa_custom.autogain:main_calibrate"` to `pyproject.toml` `[project.scripts]`

## 6. Verify

- [x] 6.1 `alexa-mic-calibrate --dry-run` — command registered and imports correctly (verified syntax + module load)
- [x] 6.2 `alexa-mic-test` — pink-noise path unbroken (23 autogain tests pass, original `run_autogain_auto()` intact)
- [x] 6.3 Test suite: 244 passed, 10 skipped (pre-existing failures: test_client.py missing livekit, test_audio.py needs /proc/asound, test_record.py phrase mismatch — all unrelated)
