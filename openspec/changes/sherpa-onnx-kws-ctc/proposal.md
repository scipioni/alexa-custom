## Why

The sherpa-onnx integration currently uses `OnlineRecognizer` for both stages, which runs full beam-search ASR continuously — unnecessarily heavy for stage-1 where only a handful of wake words need detection. On the Arduino Uno Q (Snapdragon 801, aarch64, CPU-only), always-on full ASR is a meaningful power/CPU burden. Additionally, community Italian models built on Zipformer2 CTC cannot be loaded today, limiting model choice for stage-2.

## What Changes

- **New**: `SherpaKeywordSpotter` backend for stage-1 — uses `sherpa_onnx.KeywordSpotter` with the same transducer model files already used by `SherpaOnnxSTT` (no new model download). Fires directly on configured wake words; no energy VAD or fuzzy matching needed.
- **New**: Auto-generation of the `keywords_file` required by `KeywordSpotter` at startup, derived from `wake_words` in config by reading the model's `tokens.txt` (character-level tokenisation for Italian models).
- **New**: CTC model support in `SherpaOnnxSTT` — when `model.onnx` is found in the model directory (no `joiner.onnx`), use `OnlineRecognizer.from_zipformer2_ctc()` instead of `from_paraformer()`.
- **Changed**: `STTStage1Config` gains three new optional fields: `keyword_spotter` (bool), `keywords_score` (float), `keywords_threshold` (float).
- **Changed**: `_recognition_loop` stage-1 branch gains a KWS path alongside the existing vosk and sherpa-online paths.

## Capabilities

### New Capabilities

- `sherpa-kws-wake-detection`: KeywordSpotter-based stage-1 wake-word detection — keyword file auto-generation, KWS backend init, stage-1 loop integration, config fields.

### Modified Capabilities

- `sherpa-onnx-stt`: Extend model-type auto-detection to cover Zipformer2 CTC (`model.onnx` present, no `joiner.onnx`).
- `multi-stage-stt`: `stt.stage1` block gains `keyword_spotter`, `keywords_score`, `keywords_threshold` fields.

## Impact

- `alexa_custom/stt.py` — new `SherpaKeywordSpotter` class, KWS branch in `_recognition_loop`, CTC branch in `SherpaOnnxSTT.__init__`
- `alexa_custom/config.py` — three new fields on `STTStage1Config`, parser update
- No changes to `client.py`, `audio.py`, `actions.py`, or the web dashboard
- No new model downloads required for the KWS path
- `sherpa-onnx` package version must support `KeywordSpotter` and `OnlineRecognizer.from_zipformer2_ctc` (already present in the installed version)
