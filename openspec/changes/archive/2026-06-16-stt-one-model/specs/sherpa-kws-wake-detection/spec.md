## REMOVED Requirements

### Requirement: KeywordSpotter backend for stage-1
**Reason**: The dedicated KWS cheap-gate stage is removed. Wake detection now happens by matching the single transcription model's output against the configured wake words.
**Migration**: Remove `stt.stage1.keyword_spotter` / `sherpa-hotwords` configuration. To use sherpa for recognition, set `stt.backend: sherpa-onnx`.

### Requirement: Auto-generated keywords file
**Reason**: No KWS backend means no keywords file is generated.
**Migration**: None required; the generated keywords file is no longer used.

### Requirement: KWS stage-1 loop — direct wake firing
**Reason**: The KWS-specific firing path in the recognition loop is removed in favor of the single transcribe→match loop.
**Migration**: None required.

### Requirement: Tunable KWS detection thresholds
**Reason**: KWS-specific thresholds (`keywords_score`, `keywords_threshold`, `hotwords_score`) no longer apply.
**Migration**: Remove these keys; tune wake matching via `recognition.matching_threshold` and `min_word_overlap` instead.
