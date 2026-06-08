# Capability: sherpa-kws-wake-detection

## Purpose

Wake-word detection using `sherpa_onnx.KeywordSpotter` as the stage-1 backend. When enabled, the spotter fires directly on keyword detection without relying on the energy VAD, reducing false wake events and latency on target hardware.

## Requirements

### Requirement: KeywordSpotter backend for stage-1
When `stt.stage1.backend: sherpa-onnx` and `stt.stage1.keyword_spotter: true`, the system SHALL initialise `sherpa_onnx.KeywordSpotter` using the encoder, decoder, and joiner files from the configured model directory. The system SHALL NOT initialise `OnlineRecognizer` for this stage-1 instance.

#### Scenario: KWS backend selected
- **WHEN** `stt.stage1.backend: sherpa-onnx` and `stt.stage1.keyword_spotter: true` are set
- **THEN** stage-1 initialises a `SherpaKeywordSpotter` instance (not `SherpaOnnxSTT`)

#### Scenario: KWS opt-out preserves existing behaviour
- **WHEN** `stt.stage1.keyword_spotter` is absent or `false`
- **THEN** stage-1 uses the existing `SherpaOnnxSTT` (OnlineRecognizer) path unchanged

#### Scenario: Missing model directory at KWS init
- **WHEN** `keyword_spotter: true` but the model directory does not exist
- **THEN** the system raises `RuntimeError` with a message directing the user to run `alexa-setup --sherpa-onnx`

### Requirement: Auto-generated keywords file
The system SHALL derive the `keywords_file` required by `KeywordSpotter` at daemon startup by tokenising each configured wake word and its aliases using the model's `tokens.txt`. The file SHALL be written to a temporary path and deleted when the daemon exits or the backend is garbage-collected.

#### Scenario: Keywords file generated from wake words
- **WHEN** `SherpaKeywordSpotter` is initialised with wake words `["galileo", "ehi galileo"]`
- **THEN** a temporary file is written containing one line per wake word/alias with tokens space-separated (e.g. `g a l i l e o`)

#### Scenario: Unknown character logged and skipped
- **WHEN** a wake word contains a character absent from `tokens.txt`
- **THEN** that character is skipped, a warning is logged, and the keyword line is written with the remaining tokens

#### Scenario: Temp file cleaned up on exit
- **WHEN** the `SherpaKeywordSpotter` instance is garbage-collected or explicitly reset
- **THEN** the temporary keywords file is deleted from the filesystem

### Requirement: KWS stage-1 loop — direct wake firing
When `SherpaKeywordSpotter` is the stage-1 backend, the recognition loop SHALL feed audio chunks directly to the spotter and enter command mode immediately when a keyword is detected. The energy VAD (`stage1_last_speech_t`, `stage1_speech_ms`) SHALL NOT be active.

#### Scenario: Keyword detected triggers command mode
- **WHEN** a configured wake word is spoken and `KeywordSpotter` fires
- **THEN** the system enters command mode (calls `_wake_detected`) using the detected keyword to look up the wake word group

#### Scenario: Non-keyword audio produces no action
- **WHEN** audio is fed that does not match any keyword
- **THEN** `accept_waveform` returns `False`, no wake event is emitted, and the loop continues

#### Scenario: No fuzzy matching for KWS
- **WHEN** `SherpaKeywordSpotter` is the stage-1 backend
- **THEN** the detected keyword is looked up with exact alias-map match only (no `_approx_wake_match` call)

### Requirement: Tunable KWS detection thresholds
The system SHALL expose `keywords_score` and `keywords_threshold` as configurable fields so that sensitivity can be tuned for the target hardware environment without code changes.

#### Scenario: Custom threshold applied
- **WHEN** `stt.stage1.keywords_threshold: 0.4` is set
- **THEN** `KeywordSpotter` is initialised with `keywords_threshold=0.4`

#### Scenario: Default threshold used when absent
- **WHEN** `stt.stage1.keywords_threshold` is not set in config
- **THEN** `KeywordSpotter` is initialised with `keywords_threshold=0.25`
