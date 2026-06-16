## ADDED Requirements

### Requirement: Single always-on transcription model

The system SHALL load exactly one STT model and run it continuously over the captured audio stream, producing transcripts for both wake-word and command matching. There SHALL be no separate stage-1 cheap-gate model and no stage-2 capture model.

#### Scenario: One model loaded at startup

- **WHEN** the STT worker initializes
- **THEN** it creates a single backend instance from the configured `stt.backend`
- **AND** it does not create or reference any `stage1`/`stage2` backend objects

#### Scenario: Continuous transcription while idle

- **WHEN** the daemon is idle (no active LiveKit call)
- **THEN** the single model receives every audio chunk and updates its transcript
- **AND** the worker matches the transcript against wake words and command phrases

### Requirement: Configurable transcription backend

The single model's backend SHALL be configurable via `stt.backend`, accepting at minimum `vosk` and `sherpa-onnx`. Backend-specific options (e.g. `model_path`, `num_threads`) SHALL be configurable under `stt`.

#### Scenario: Vosk backend selected

- **WHEN** `stt.backend` is `vosk`
- **THEN** the worker loads a Vosk free-vocabulary recognizer as the single model

#### Scenario: Sherpa backend selected

- **WHEN** `stt.backend` is `sherpa-onnx`
- **THEN** the worker loads a sherpa-onnx recognizer as the single model

#### Scenario: Invalid backend rejected

- **WHEN** `stt.backend` is not a supported value
- **THEN** config loading raises a `ConfigError` naming the offending value

### Requirement: Endpoint-gated matching with confirmation tone

The system SHALL act on a matched wake word or command only once the utterance is followed by silence (a VAD/endpoint event). On a confirmed match the system SHALL emit a "good tone".

#### Scenario: Match confirmed on silence

- **WHEN** the transcript matches a wake word or command phrase
- **AND** the speaker stops (silence ≥ `stt.vad_silence_ms`) or the backend reports an endpoint
- **THEN** the system emits the configured good tone
- **AND** proceeds to dispatch / wake-state handling

#### Scenario: No tone before silence

- **WHEN** a partial transcript matches but speech is ongoing
- **THEN** no tone is emitted and no dispatch occurs until the endpoint

### Requirement: Single recognition loop

The worker SHALL implement recognition in a single transcribe→match→gate→tone→dispatch loop, without `recognition.mode` branching or separate per-backend (`is_kws`/`is_vosk`/`else`) firing paths.

#### Scenario: Backend differences hidden behind one interface

- **WHEN** any supported backend is configured
- **THEN** the same loop drives it via a common transcript/endpoint interface
- **AND** there is no `two-stage` vs `single-stage` mode selector
