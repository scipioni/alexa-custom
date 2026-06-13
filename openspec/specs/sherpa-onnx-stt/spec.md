# Capability: sherpa-onnx-stt

## Purpose

Sherpa-onnx streaming STT as an alternative backend to Vosk. When configured via `stt.backend: sherpa-onnx`, the STT pipeline uses the sherpa-onnx Paraformer-ita OnlineRecognizer instead of Vosk.

## Requirements

### Requirement: sherpa-onnx backend selection
The system SHALL support `stt.backend: sherpa-onnx` in `config.yaml`. When selected, the STT pipeline SHALL use the sherpa-onnx OnlineRecognizer.

#### Scenario: Sherpa-onnx backend configured
- **WHEN** `stt.backend: sherpa-onnx` is set in `config.yaml`
- **THEN** the STT pipeline initializes `sherpa_onnx.OnlineRecognizer` with the Italian Paraformer model

#### Scenario: Vosk remains default
- **WHEN** `stt.backend` is absent or set to `vosk` in `config.yaml`
- **THEN** the system uses the existing Vosk pipeline (no change to existing behavior)

### Requirement: sherpa-onnx model type auto-detection
The system SHALL auto-detect the sherpa-onnx model architecture from the files present in the model directory and select the appropriate `OnlineRecognizer` factory:

1. If `joiner.onnx` or `joiner.int8.onnx` is present → `OnlineRecognizer.from_transducer()`
2. Else if `model.onnx` is present → `OnlineRecognizer.from_zipformer2_ctc()`
3. Else → `OnlineRecognizer.from_paraformer()`

If `from_zipformer2_ctc` is not available in the installed `sherpa_onnx` version, the system SHALL fall through to `from_paraformer` and log a warning.

#### Scenario: Transducer model detected
- **WHEN** the model directory contains `joiner.onnx` (or `joiner.int8.onnx`)
- **THEN** `OnlineRecognizer.from_transducer()` is called with encoder, decoder, and joiner paths

#### Scenario: Zipformer2 CTC model detected
- **WHEN** the model directory contains `model.onnx` but no `joiner.onnx`
- **THEN** `OnlineRecognizer.from_zipformer2_ctc()` is called with `model.onnx` as the model path

#### Scenario: Paraformer model used as final fallback
- **WHEN** the model directory contains neither `joiner.onnx` nor `model.onnx`
- **THEN** `OnlineRecognizer.from_paraformer()` is called

#### Scenario: from_zipformer2_ctc unavailable in installed version
- **WHEN** `model.onnx` is present but `sherpa_onnx.OnlineRecognizer` does not have `from_zipformer2_ctc`
- **THEN** the system logs a warning and falls through to `from_paraformer()`

### Requirement: Model download
The system SHALL download the sherpa-onnx NeMo FastConformer CTC model via `alexa-setup --sherpa-onnx` and store it under `models/sherpa-onnx/nemo-ctc-it/`.

#### Scenario: Model download
- **WHEN** the user runs `alexa-setup --sherpa-onnx`
- **THEN** the NeMo CTC ONNX model and tokens are downloaded to `models/sherpa-onnx/nemo-ctc-it/`

#### Scenario: Missing model at startup
- **WHEN** `stt.backend: sherpa-onnx` or `stt.stage<N>.backend: nemo-offline` is configured but the model is not present
- **THEN** the system logs an error with guidance to run `alexa-setup --sherpa-onnx` and exits with a non-zero status

### Requirement: Backend-agnostic trigger matching
The wake word and command trigger matching logic SHALL remain identical regardless of which STT backend is active.

#### Scenario: Wake word detected via sherpa-onnx
- **WHEN** a configured wake word is spoken and recognized by sherpa-onnx
- **THEN** the system plays the wake beep and opens the command listening window exactly as with Vosk

#### Scenario: Command matched after wake word
- **WHEN** a command phrase is recognized within the command timeout window
- **THEN** the corresponding trigger actions are dispatched identically to the Vosk backend
