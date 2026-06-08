## MODIFIED Requirements

### Requirement: stt.stage1 configuration block
The `stt.stage1` block in `conf/config.yaml` SHALL accept:

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | str | `"vosk"` | `"vosk"` or `"sherpa-onnx"` |
| `model_path` | str\|null | `"models/it"` | Path to model directory |
| `confidence` | float | `0.65` | Vosk word confidence threshold (ignored for sherpa-onnx) |
| `vad_silence_ms` | int | `500` | Silence duration (ms) triggering stage-1 finalization (sherpa energy VAD; not used when `keyword_spotter: true`) |
| `rms_threshold` | float | `0.02` | Minimum RMS to count as speech in stage-1 energy VAD (not used when `keyword_spotter: true`) |
| `min_speech_ms` | int | `300` | Minimum sustained speech before silence timer can fire (not used when `keyword_spotter: true`) |
| `keyword_spotter` | bool | `false` | When `true` and `backend: sherpa-onnx`, use `KeywordSpotter` instead of `OnlineRecognizer` for stage-1 |
| `keywords_score` | float | `1.0` | Keyword token boost weight (passed to `KeywordSpotter`; ignored when `keyword_spotter: false`) |
| `keywords_threshold` | float | `0.25` | Keyword detection threshold (passed to `KeywordSpotter`; ignored when `keyword_spotter: false`) |

#### Scenario: Stage 1 confidence threshold applied
- **WHEN** `stt.stage1.confidence: 0.8` is set and Vosk returns a wake word with confidence 0.75
- **THEN** the wake word is NOT accepted and the system stays in stage 1

#### Scenario: Stage 1 confidence threshold met
- **WHEN** `stt.stage1.confidence: 0.65` is set and Vosk returns confidence 0.70
- **THEN** the wake word IS accepted and the system transitions to stage 2

#### Scenario: keyword_spotter fields parsed and passed through
- **WHEN** `keyword_spotter: true`, `keywords_score: 1.5`, `keywords_threshold: 0.3` are set
- **THEN** `STTStage1Config` has `keyword_spotter=True`, `keywords_score=1.5`, `keywords_threshold=0.3`

#### Scenario: keyword_spotter absent defaults to false
- **WHEN** `stt.stage1` block has no `keyword_spotter` key
- **THEN** `STTStage1Config.keyword_spotter` is `False` and existing behaviour is unchanged
