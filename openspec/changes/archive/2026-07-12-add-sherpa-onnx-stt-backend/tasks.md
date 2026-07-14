## 1. Resolve open questions (blocking)

- [x] 1.1 Confirm the exact Kroko IT model download source/URL — resolved: `hudaiapa88/sherpa-stt-onnx` on HuggingFace (Apache 2.0), `it/kroko_64l/` and `it/kroko_128l/` subdirs, each with `encoder.int8.onnx`/`decoder.int8.onnx`/`joiner.int8.onnx`/`tokens.txt` — verified byte-size-identical to the files already present locally on this board (both variants checked). Third-party re-upload, not an official Banafo/k2-fsa catalog entry — acceptable given the exact match, but note this in setup.py in case it disappears.
- [x] 1.2 Decide whether sherpa-onnx lives behind the existing `asr-eval` optional extra or a new dedicated extra — decided: reuse the existing `asr-eval` extra unchanged (already pins the exact same `sherpa-onnx==1.13.3`; a second extra with identical contents would just be duplicate maintenance surface).
- [x] 1.3 **Discovered mid-implementation**: sherpa-onnx was already built and removed from this project once before (commits `657f57c`, `b5a2412`), with a documented benchmark showing it losing to Vosk on load time (40s vs 2.8s), CPU (103% vs 66-70%), endpoint latency, and transcript fragmentation (`docs/stt-simple.md`). User decision (this session): proceed as a *second attempt*, hard-gated on (a) fixing and re-running `scripts/bench_stt.py` for a real before/after comparison, and (b) not reintroducing the "any config change stalls the daemon ~40-50s" risk. Both addressed below.
- [x] 1.4 Backend config value naming: use `sherpa-onnx` (hyphenated) for `stt.backend`, matching the pre-existing (pre-removal) convention already sitting in `conf.example/config.yaml`'s comment and `scripts/bench_stt.py`'s docstring — not `sherpa_onnx` (underscore), which would've been a needless, inconsistent third convention.

## 2. Model provisioning (serena-setup)

- [x] 2.1 Add `download_sherpa_onnx_kroko(variant: str = "64l", force: bool = False)` to `alexa_custom/setup.py`, following the existing `download_vosk`/`_download` pattern
- [x] 2.2 Add `download_silero_vad(force: bool = False)` to `alexa_custom/setup.py`, downloading to `models/vad/silero_vad.onnx`
- [x] 2.3 Add CLI flags to `serena-setup`'s `main()`: `--sherpa-onnx-model {64l,128l}` (default `None` — opt-in, not `--skip-*` like Vosk/Piper since this is additive, not on-by-default)
- [x] 2.4 Verify default `serena-setup` invocation (no new flags) is unaffected — confirmed: `args.sherpa_onnx_model` defaults to `None`, download only runs when explicitly passed. Also verified the skip-if-present branch works correctly against the models already on this board.

## 3. Config

- [x] 3.1 Add `sherpa_vad_threshold: float = 0.5`, `sherpa_vad_min_speech_ms: int = 100`, `sherpa_vad_min_silence_ms: int = 400` to `STTConfig` in `alexa_custom/config.py`
- [x] 3.2 Confirm `stt.backend` validation accepts `sherpa-onnx` alongside `vosk` (raise `ConfigError` for anything else, per existing "Invalid backend rejected" scenario)
- [x] 3.3 Add the new fields (commented, matching existing style) to `conf.example/config.yaml` and `conf/config.yaml`
- [x] 3.4 Document that `model_path` for `stt.backend: sherpa-onnx` points at a Kroko model directory (default `models/it/kroko_64l`)
- [x] 3.5 Confirm the three new `sherpa_vad_*` fields are deliberately **excluded** from `_get_backend_key()` in `stt.py` — verified (`grep sherpa_vad alexa_custom/stt.py` → no matches; `_get_backend_key` untouched by this change), so they don't trigger a full (~40-50s) backend reload on hot-reload. Changing them requires a `model_path`/`num_threads` change or daemon restart to take effect.

## 4. Backend implementation

- [x] 4.1 Add `SherpaOnnxSTT(STTBackend)` to `alexa_custom/stt_backends.py`: constructor loads the Kroko `OnlineRecognizer` (`from_transducer`, tokens/encoder/decoder/joiner from `model_path`) and a Silero `VoiceActivityDetector`, plus a pre-roll ring buffer
- [x] 4.2 Implement `accept_waveform(data: bytes) -> bool`: convert to float32, feed the internal VAD, feed the Kroko stream + drain via `is_ready()`/`decode_stream()` only while VAD reports speech (skip otherwise — the CPU-saving gate), flush pre-roll on the silence→speech transition, always return `False` (endpoint decisions stay with `stt.py`'s existing RMS-based `vad_fire`)
- [x] 4.3 Implement `text()` / `partial_text()` via `recognizer.get_result(stream)`
- [x] 4.4 Implement `finalize()`: pad any shortfall against the ~0.66s Zipformer right-context requirement with zeros (real trailing audio was already fed via ordinary `accept_waveform()` calls under `stt.py`'s existing silence timers), call `stream.input_finished()`, drain, return `get_result(stream)`
- [x] 4.5 Implement `reset()`: recreate a fresh `OnlineStream`
- [x] 4.6 Wire `get_stt_backend()` in `alexa_custom/stt_backends.py` to branch on `cfg.backend`, constructing `SherpaOnnxSTT` for `sherpa-onnx` and raising a clear `RuntimeError` (naming the install command) if the `sherpa_onnx` Python package isn't importable
- [x] 4.7 Confirm no changes needed in `alexa_custom/stt.py`'s recognition loop — the new backend must satisfy the existing `STTBackend` contract as-is

## 5. Dependencies

- [x] 5.1 Add `sherpa-onnx==1.13.3` to the `asr-eval` extra's comment/usage to reflect dual purpose (pinned — 1.13.4's aarch64 wheel is broken, verified this session)
- [x] 5.2 Verify `uv sync` with/without this extra doesn't disturb unrelated optional deps — already installed and verified working (`SherpaOnnxSTT` constructed and ran successfully above with `gi`/`Gst` still importable from earlier in this session)

## 6. Validation (hard gate before calling this viable — not optional)

- [x] 6.1 Fix `scripts/bench_stt.py`: stale `STTStage2Config` import (class no longer exists post single-model refactor) → `STTConfig`; re-add `sherpa-onnx` to its `--backend` choices
- [x] 6.2 Ran `scripts/bench_stt.py --backend vosk --backend sherpa-onnx --feed silence --duration 30` (no mic). Results:
  | Metric | vosk | sherpa-onnx (this change) | sherpa-onnx (historical, removed) |
  |---|---|---|---|
  | Load time | 3.3s | **44.3s** | 40s |
  | CPU (idle/silence) | 99% | **93%** | 103% |
  | RTF avg/p95 | 0.24 / 0.90 | **0.07 / 0.09** | n/a |

  VAD-gating clearly helps CPU/RTF *while idle* (93% vs the historical 103%, and well below vosk here) — but load time is unchanged and still ~40-50s.
- [x] 6.3 Ran `scripts/bench_stt.py --backend vosk --backend sherpa-onnx --wav <piper-synthesized "accendi le luci" + 2s trailing silence>`. Results:
  | Metric | vosk | sherpa-onnx (this change) | sherpa-onnx (historical, removed) |
  |---|---|---|---|
  | Endpoint latency | 808ms | **1114ms** | 1806ms |
  | CPU (active speech) | 92% | **172%** | n/a |
  | Transcript | "accendi le luci" | "Accendi le luci" (correct, both) | "fragmented" |

  Endpoint latency is better than the historical number but still ~40% slower than vosk. CPU during *active* speech is markedly higher than vosk (172% vs 92%) — the VAD gate's saving only applies while idle; once speech starts, the full Zipformer encoder cost applies, exceeding one core. No fragmentation observed on this single test phrase (unlike the historical complaint) — but this is one phrase, not the exhaustive testing the original benchmark presumably used.
- [x] 6.4 **Mixed result, not a clean win** — reported back to the user (see conversation) rather than silently proceeding:
  - **Improved**: idle CPU (93% vs 103%), endpoint latency (1114ms vs 1806ms), no fragmentation observed (single-phrase test)
  - **Unresolved**: load time (44-49s, unaffected by any change in this session — inherent to the model/onnxruntime, not fixable by VAD-gating)
  - **New finding**: active-speech CPU is *worse* than vosk (172% vs 92%) — over one full core, a trade-off the original historical benchmark didn't break out this way
- [x] 6.5 Confirm `stt.backend: vosk` (default, no config changes) behaves identically to before this change — confirmed: `get_stt_backend(STTConfig())` still constructs `VoskSTT` in 3.3s; existing `tests/test_config.py`/`test_stt_heartbeat.py`/`test_web_config.py` (72 tests) all pass unchanged.
- [ ] 6.6 **Requires live mic — user action, not done in this session**: manually re-run the three `docs/asr-plan.md` test phrases ("accendi le luci", "il legno è nero", "ascolta assistente") against the real backend (not `asr_eval.py`, set `stt.backend: sherpa-onnx` in `conf/config.yaml` and run `serena-stt` or the full daemon)
- [x] 6.7 Ran `task test`-equivalent (`pytest` scoped away from an unrelated pre-existing broken `tests/test_llm.py` — stale `OllamaClient` import, not touched by this change) plus `ruff check`/`ruff format`. Added `tests/test_sherpa_onnx_backend.py` (model-file-check + backend-selection error paths, no real model/mic needed — fast) and 3 new cases in `tests/test_config.py` for the new config fields. 80 tests pass.

## 7. Documentation

- [x] 7.1 Documented `stt.backend: sherpa-onnx` and its new config fields in `docs/stt-simple.md`, `docs/configuration.md`, and `AGENTS.md`/`CLAUDE.md` (symlinked) — including the real benchmark numbers from 6.2/6.3, not aspirational ones
- [x] 7.2 Noted the known quiet-trailing-syllable limitation (from `docs/asr-plan.md`) applies here too, and isn't backend-specific (`docs/stt-simple.md`)
- [x] 7.3 Updated `docs/stt-simple.md`'s "sherpa-onnx (removed)" framing to "opt-in, non-default" with the real before/after comparison table
