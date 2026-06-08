## Context

The current sherpa-onnx stage-1 path runs `OnlineRecognizer` (full transducer beam search) continuously, then fuzzy-matches the ASR transcript against wake words. This works but is wasteful on the Arduino Uno Q (Snapdragon 801, 4× Cortex-A15, CPU-only): the full decoder is engaged even when the user says nothing remotely like a wake word.

`sherpa_onnx.KeywordSpotter` uses the same encoder/decoder/joiner model files as `OnlineRecognizer` but applies a keyword-boosted modified beam search that fires only when a registered keyword sequence is detected. It is designed for always-on wake-word detection at lower CPU cost.

The stage-2 path currently supports only transducer and paraformer models. Many community Italian models are Zipformer2 CTC (single `model.onnx`, no joiner), and these fail silently today because `SherpaOnnxSTT.__init__` falls through to `from_paraformer()` with wrong file paths.

## Goals / Non-Goals

**Goals:**
- Add `SherpaKeywordSpotter` as a third `STTBackend` implementation, usable only for stage-1
- Auto-generate the `keywords_file` at runtime from config wake words + model `tokens.txt` (no extra file to manage on the board)
- Add Zipformer2 CTC model support to `SherpaOnnxSTT` via file-based auto-detection
- Keep the existing vosk and sherpa-online stage-1 paths fully unchanged
- Expose `keywords_score` and `keywords_threshold` as tunable config fields (need hardware tuning on Uno Q)

**Non-Goals:**
- WenetCTC / NemoCTC / TOneCTC model support (can be added later by the same pattern)
- Offline recognizer support (Whisper etc.)
- Dynamic keyword re-enrollment without daemon restart
- BPE tokeniser support for auto-generation (character-level only for now)

## Decisions

### D1: Same model files for KWS and OnlineRecognizer

`KeywordSpotter.__init__` takes `encoder`, `decoder`, `joiner` — identical to `from_transducer()`. The existing kroko_128l download already contains these. No new model is needed; `get_stt_backend()` routes to `SherpaKeywordSpotter` when `keyword_spotter: true` in stage-1 config, passing the same `model_path`.

**Alternative considered**: dedicated smaller KWS model. Rejected — no Italian KWS-specific model available; adds a new download; the transducer model with keyword boosting is the documented approach.

### D2: Auto-generate keywords file from tokens.txt

On `SherpaKeywordSpotter.__init__`:
1. Read `tokens.txt` from model dir → build `char → token_id` map (format: `<symbol> <id>` per line)
2. For each wake word + alias from the `keywords` list (passed at construction): tokenize by greedy character-level lookup against the vocab
3. Write to a `tempfile.NamedTemporaryFile` (not deleted on close, deleted on `__del__` / explicit cleanup)
4. Pass temp path to `KeywordSpotter(keywords_file=...)`

**Alternative considered**: require user-provided static keywords file via config. Rejected — adds an extra artefact to manage on the board; disconnects from config wake words; generates drift bugs.

**Alternative considered**: pass `keywords` string directly to `KeywordSpotter`. Rejected — sherpa-onnx `KeywordSpotter` requires a file path, not an inline string.

**Character-level assumption**: Italian models in the sherpa-onnx ecosystem (kroko family) use character-level tokens. A `tokens.txt` entry looks like `a 1`. If a token for a character is missing, we skip it and log a warning. This is sufficient for current models; BPE support can be added later.

### D3: CTC detection via model.onnx presence

Extend `SherpaOnnxSTT.__init__` detection chain:

```
joiner.onnx (or joiner.int8.onnx) present?  → from_transducer()
model.onnx present?                           → from_zipformer2_ctc()
fallback                                      → from_paraformer()
```

`from_zipformer2_ctc()` requires `tokens`, `model` (path to `model.onnx`), `sample_rate`, `feature_dim`, `num_threads`, `provider`, endpoint detection params.

**Alternative considered**: explicit `model_type` config field for CTC disambiguation. Rejected per user preference; file-based detection is consistent with the existing transducer/paraformer pattern.

**Scope**: Only `zipformer2_ctc` for now — it's the dominant architecture for community Italian models. `wenet_ctc` / `nemo_ctc` also use `model.onnx` but their `from_*` calls differ in minor ways; add when a user actually brings such a model.

### D4: STTBackend interface fit for KWS

`SherpaKeywordSpotter` maps to `STTBackend` as follows:

| Method | KWS behaviour |
|--------|--------------|
| `accept_waveform(data)` | Feed chunk; return `True` when keyword detected (clears internal state via `reset_stream`) |
| `text()` | Return last detected keyword string (set inside `accept_waveform` on hit) |
| `partial_text()` | Return `""` — KWS has no intermediate partials |
| `reset()` | Create new stream, clear `_last_keyword` |
| `finalize()` | Return `""` — not applicable |

The stage-1 loop already handles `accept_waveform → True` as "endpoint reached, get text, check wake match". For KWS this is exactly correct: True = keyword fired, `text()` = which keyword.

### D5: Stage-1 loop KWS branch

In `_recognition_loop`, add a third type check alongside `is_vosk` / sherpa-online:

```python
is_kws = isinstance(stage1_backend, SherpaKeywordSpotter)
```

KWS branch per chunk:
- Feed `accept_waveform(data)` 
- If True: `text()` → exact alias_map lookup → `_wake_detected(...)` 
- If False: continue (no energy VAD, no partial tracking)

The energy VAD variables (`stage1_last_speech_t`, `stage1_speech_ms`) are not initialised when `is_kws`, keeping the code clean.

### D6: New config fields on STTStage1Config

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `keyword_spotter` | `bool` | `False` | Opt-in to KWS mode; requires `backend: sherpa-onnx` |
| `keywords_score` | `float` | `1.0` | Keyword token boost weight during beam search |
| `keywords_threshold` | `float` | `0.25` | Trigger probability threshold |

`get_stt_backend()` for stage-1 receives the wake-word list (new parameter) so it can pass keywords to `SherpaKeywordSpotter`.

## Risks / Trade-offs

**[Risk] Character tokenisation fails for unusual wake words** → Mitigation: log a warning per unresolvable character; skip that wake-word variant (system still works with others). Add test case.

**[Risk] KWS fires more false positives than energy-VAD sherpa path** → Mitigation: `keywords_threshold` is configurable; default 0.25 is conservative. User can raise it on the Uno Q after testing.

**[Risk] `from_zipformer2_ctc` call signature differs from installed sherpa-onnx version** → Mitigation: guard with `hasattr(sherpa_onnx.OnlineRecognizer, 'from_zipformer2_ctc')` and fall through to `from_paraformer` with a warning if absent.

**[Risk] Temp keywords file not cleaned up on crash** → Mitigation: use `tempfile` in the system temp dir (auto-cleaned on reboot); also implement `__del__` cleanup.

## Migration Plan

1. Deploy new code — existing configs with `keyword_spotter` absent default to `False`, so all existing behaviour is unchanged.
2. To opt in on Uno Q: add `keyword_spotter: true` to `stt.stage1` in `conf/config.yaml`. Restart daemon.
3. Tune `keywords_threshold` / `keywords_score` if false-positive rate is too high or wake word is missed.
4. No rollback needed — removing `keyword_spotter: true` restores previous behaviour.

## Open Questions

- None blocking implementation.
