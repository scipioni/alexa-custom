## 1. Scope & on-board validation

- [x] 1.1 Audit `conf/actions/*.yaml` for scoped triggers. **Done**: only `chiama assistenza` → `[help]` is cross-group; safe to make `with_wake: true`. No escape hatch needed — scoping dropped.
- [x] 1.2 Benchmark single always-on backend on board (`scripts/bench_stt.py`). **Done**: vosk — load 2.8s, CPU 66–70% (mic), RTF p95 0.39–0.75, clean full transcripts, latency p95 1059ms, 0 false fires. sherpa-onnx — load 40s, CPU 103%, fragmented utterances, latency p95 1806ms. → **default `stt.backend: vosk`**, `vad_silence_ms: 900`; sherpa kept configurable.
- [x] 1.3 Set default backend (`vosk`) and `vad_silence_ms` (~900ms) in the new config schema (tasks 2.1/2.2/6.1) from benchmark findings.

## 2. Config schema

- [x] 2.1 `config.py`: add `STTConfig` fields (`backend`, `model_path`, `num_threads`, `vad_silence_ms`, `rms_threshold`, `adaptive_rms`, `adaptive_rms_margin`, `min_speech_ms`, `wake_match_threshold`); remove `stage1`/`stage2` and their parsers.
- [x] 2.2 `config.py`: `RecognitionConfig` — remove `mode`, `partial_matching`, `kws_one_breath`, `partial_stability_ms/reads`, `command_timeout`, `command_max_timeout`; add `wake_window`.
- [x] 2.3 `config.py`: `Trigger` — add `commands: list[str]` and `with_wake: bool` (default true); retain `patterns`; fold legacy `phrase`+`aliases` into `commands` with a deprecation warning; stop using `wake_words` for partitioning.
- [x] 2.4 `config.py`: parse `wake_words` as a flat `list[str]`; remove `WakeWordGroup`, `_parse_wake_word_groups`, `_build_alias_map`, group-id resolution, and `WakeWordGroup.triggers` merging.
- [x] 2.5 `config.py`: `_parse_actions_config` — build a single flat `ActionsConfig.triggers`; remove `direct_triggers` partitioning and per-group scoped-trigger resolution.
- [x] 2.6 `config.py`: parse `on_reply` triggers with the `commands` shape (fold legacy phrase/aliases); `with_wake` ignored for reply triggers.
- [x] 2.7 `config.py`: emit `ConfigError`/warnings for removed/legacy keys (`recognition.mode`, `stt.stage1/stage2`, `vosk_grammar`, `keyword_spotter`, `wake_words` group mappings, trigger `wake_words:`) pointing to the new equivalents.

## 3. Backends

- [x] 3.1 `stt_backends.py`: ensure `vosk` and `sherpa-onnx` expose the common `STTBackend` interface for free-vocab transcription as a single model; `get_stt_backend` builds one model from `stt.backend`.
- [x] 3.2 Remove `SherpaKeywordSpotter`, `sherpa-hotwords`, grammar helpers (`_grammar_json`, `_grammar_json_all`, `_phrases_to_grammar`) and their references once unused.

## 4. Single recognition loop

- [x] 4.1 `stt.py`: implement `_recognition_loop` as one transcribe→match→gate→tone→dispatch loop over `_iter_gated_audio`, keeping the RMS/VAD energy front-gate and `post_playback`/cooldown handling.
- [x] 4.2 Implement wake matching on finalized transcript (fuzzy via `wake_match_threshold`), emit good tone, open the recently-woken window (`wake_deadline = now + wake_window`).
- [x] 4.3 Implement one-breath handling: strip wake tokens, match residual against `with_wake: true` triggers within the same utterance.
- [x] 4.4 Implement command matching: iterate triggers, skip `with_wake: true` when not woken, fuzzy-match `commands`, emit tone, dispatch, apply cooldown.
- [x] 4.5 Wire LLM no-match fallback to the new flow (unchanged semantics).
- [x] 4.6 Delete `_single_stage_loop`, the `is_kws`/`is_vosk`/sherpa firing branches, `_match_full_intent`, intent-map building, and stage1/stage2 reload logic in `run_stt_worker`.

## 5. Web config panel & trigger canvas

- [x] 5.1 `web.py`: update the config panel fields to the new schema (single backend, `wake_window`; remove stage1/stage2, grammar, partial-matching, KWS controls).
- [x] 5.2 `web.py`: update the graph/config payload sent to the dashboard to the flat model — a `wake_words` string list and a flat `triggers` list carrying `with_wake` (drop `global_triggers`/per-group `triggers` structure).
- [x] 5.3 `dashboard.js`: rewrite `_buildGraphData` + canvas render to the two-node layout — one wake-words node + one rectangular triggers node in a grid; highlight `with_wake: false` cells; keep `_graphFlashByPhrase` runtime match-flash working against `commands`.
- [x] 5.4 `dashboard.html`/`dashboard.css`: no structural changes required — existing canvas wrapper and node styles work with the new layout (direct_match orange highlight reused for with_wake: false).

## 6. Config files & docs

- [x] 6.1 Migrate `conf/config.yaml` to the new `stt`/`recognition` schema (single `stt.backend`/`model_path`, `recognition.wake_window`; drop stage1/stage2/mode/grammar/partial knobs).
- [x] 6.2 Rewrite `conf/actions/system.yaml`: flatten `wake_words` to a string list; `wake_words: []` → `with_wake: false`; global → `with_wake: true`; fold `aliases` into `commands`; keep `patterns`; drop the `default` group `id`. Updated header schema comment.
- [x] 6.3 Rewrite `conf/actions/user.yaml`: merge `aiuto`/`aiutami` wake aliases into flat `wake_words`; `chiama Stefano []` → `with_wake: false`; `chiama assistenza [help]` → `with_wake: true`; convert `on_reply` yes/no triggers to `commands`; keep `accendi la luce` patterns; drop `skip_unmatched_inline`.
- [x] 6.4 Update CLAUDE.md and `docs/` (audio/STT notes) to describe the single-model design; fold in `docs/stt-simple.md`.

## 7. Tests

- [x] 7.1 Update/replace wake-detection, streaming-intent, multi-stage, and sherpa-kws test suites for the single-model loop and `with_wake` model.
- [x] 7.2 Add tests for `with_wake` gating, the recently-woken window/timeout, and one-breath firing.
- [x] 7.3 Run `task test` and the `test-stt-e2e` skill; confirm green. **366 passed, 1 skipped.**
