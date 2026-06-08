## 1. Config layer

- [x] 1.1 Add `keyword_spotter: bool = False`, `keywords_score: float = 1.0`, `keywords_threshold: float = 0.25` fields to `STTStage1Config` in `config.py`
- [x] 1.2 Parse the three new fields in `_parse_stt_stage1_config()` with correct types and defaults
- [x] 1.3 Add test in `tests/test_config.py` covering: new fields parsed correctly; absent fields default correctly

## 2. SherpaKeywordSpotter backend

- [x] 2.1 Implement `_tokenize_keyword(word: str, vocab: dict[str, str]) -> str` helper in `stt.py` — reads char→token mapping from `tokens.txt`, returns space-separated token string, logs warning for unknown chars
- [x] 2.2 Implement `SherpaKeywordSpotter(STTBackend)` class in `stt.py`:
  - `__init__(model_dir, keywords: list[str], keywords_score, keywords_threshold)` — reads `tokens.txt`, generates temp keywords file, constructs `sherpa_onnx.KeywordSpotter`
  - `accept_waveform(data) -> bool` — feed chunk, decode, return True + set `_last_keyword` when keyword fires, call `reset_stream` after hit
  - `text() -> str` — return `_last_keyword`
  - `partial_text() -> str` — return `""`
  - `reset() -> None` — create new stream, clear `_last_keyword`
  - `finalize() -> str` — return `""`
  - `__del__` — delete temp keywords file
- [x] 2.3 Add unit test for `_tokenize_keyword` with a mock `tokens.txt` (known Italian chars)
- [x] 2.4 Add unit test for `SherpaKeywordSpotter.accept_waveform` using a mock `sherpa_onnx.KeywordSpotter` (monkeypatch)

## 3. CTC model support in SherpaOnnxSTT

- [x] 3.1 In `SherpaOnnxSTT.__init__`, extend the model-detection chain: after the joiner check, add `elif os.path.exists(model_onnx): from_zipformer2_ctc(...)` with `hasattr` guard for older sherpa versions
- [x] 3.2 Add unit test: mock model dir with only `model.onnx` + `tokens.txt` → assert `from_zipformer2_ctc` is called (monkeypatch `sherpa_onnx`)

## 4. Backend routing

- [x] 4.1 Update `get_stt_backend()` signature to accept `keywords: list[str] | None = None` for stage-1 routing
- [x] 4.2 In `get_stt_backend()`: when `cfg.backend == "sherpa-onnx"` and `isinstance(cfg, STTStage1Config)` and `cfg.keyword_spotter`, instantiate `SherpaKeywordSpotter` instead of `SherpaOnnxSTT`
- [x] 4.3 Update `run_stt_worker()` to pass wake word + alias list when calling `get_stt_backend` for stage-1

## 5. Recognition loop — KWS branch

- [x] 5.1 In `_recognition_loop`, add `is_kws = isinstance(stage1_backend, SherpaKeywordSpotter)` alongside `is_vosk`
- [x] 5.2 Add KWS branch in the per-chunk loop: when `is_kws`, call `accept_waveform`; on True, do exact alias-map lookup on `text()`, call `_wake_detected` if matched; no energy VAD tracking
- [x] 5.3 Ensure `_on_playback_end` resets KWS stream correctly (call `stage1_backend.reset()`)

## 6. Tests & verification

- [x] 6.1 Run `task test` — all existing tests pass
- [x] 6.2 Run `task lint` — no lint errors
- [ ] 6.3 Manual smoke test: start daemon with `keyword_spotter: false` (default) — confirm existing behaviour unchanged
- [ ] 6.4 Manual smoke test on Uno Q: `keyword_spotter: true` — confirm wake word fires correctly via KWS path (check logs for "Stage1 KWS hit" lines)
