# Capability: nemo-offline-stt

## Purpose

Offline NeMo FastConformer CTC STT backend for stage-2 command transcription. When configured via `stt.stage2.backend: nemo-offline`, the STT pipeline buffers audio during capture and transcribes the complete utterance using `OfflineRecognizer.from_nemo_ctc()`.

## ADDED Requirements

### Requirement: Backend selection
The system SHALL support `stt.stage2.backend: nemo-offline` in `config.yaml`. When selected, the STT pipeline SHALL use `sherpa_onnx.OfflineRecognizer.from_nemo_ctc()` with the configured model.

#### Scenario: nemo-offline backend configured
- **WHEN** `stt.stage2.backend: nemo-offline` is set in `config.yaml`
- **THEN** the STT pipeline initialises `NeMoOfflineSTT` with `OfflineRecognizer.from_nemo_ctc()` using the model at the configured `model_path`

#### Scenario: Unsupported in stage 1
- **WHEN** `stt.stage1.backend: nemo-offline` is set in `config.yaml`
- **THEN** the system SHALL raise a configuration error (offline backends not supported for wake-word detection)

### Requirement: Buffer-then-transcribe pattern
The `NeMoOfflineSTT` backend SHALL buffer all audio chunks in `accept_waveform()` and run full transcription in `finalize()`.

#### Scenario: Audio buffered during capture
- **WHEN** audio chunks are fed to `accept_waveform()`
- **THEN** the method returns `False` and accumulates the samples in an internal buffer

#### Scenario: Transcription on finalize
- **WHEN** `finalize()` is called
- **THEN** all buffered audio is concatenated, converted to float32, fed to `OfflineRecognizer`, and the transcribed text is returned

#### Scenario: No partial results
- **WHEN** `partial_text()` is called during capture
- **THEN** an empty string is returned

### Requirement: Model download
The system SHALL download the NeMo FastConformer CTC model via `alexa-setup --sherpa-onnx` and store it under `models/sherpa-onnx/nemo-ctc-it/`.

#### Scenario: Model download
- **WHEN** the user runs `alexa-setup --sherpa-onnx`
- **THEN** the NeMo CTC ONNX model and tokens are downloaded to `models/sherpa-onnx/nemo-ctc-it/`

#### Scenario: Missing model at startup
- **WHEN** `stt.stage2.backend: nemo-offline` is configured but the model is not present
- **THEN** the system logs an error with guidance to run `alexa-setup --sherpa-onnx` and exits with a non-zero status
