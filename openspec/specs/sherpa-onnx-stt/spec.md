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

### Requirement: Model download
The system SHALL download the sherpa-onnx Italian Paraformer model via `alexa-setup --sherpa-onnx` and store it under `models/sherpa-onnx/`.

#### Scenario: Model download
- **WHEN** the user runs `alexa-setup --sherpa-onnx`
- **THEN** the sherpa-onnx Paraformer-ita ONNX model is downloaded to `models/sherpa-onnx/`

#### Scenario: Missing model at startup
- **WHEN** `stt.backend: sherpa-onnx` is configured but the model is not present
- **THEN** the system logs an error and exits with a non-zero status

### Requirement: Equivalent recognition behavior
The sherpa-onnx backend SHALL produce partial and final text results equivalent to the Vosk backend for the same audio input.

#### Scenario: Partial results during speech
- **WHEN** audio is being captured with sherpa-onnx backend active
- **THEN** partial transcription text is available via `recognizer.text` property after each AcceptWaveform call

#### Scenario: Final result after silence
- **WHEN** the VAD detects end of speech
- **THEN** `recognizer.text` returns the final transcribed text

### Requirement: Backend-agnostic trigger matching
The wake word and command trigger matching logic SHALL remain identical regardless of which STT backend is active.

#### Scenario: Wake word detected via sherpa-onnx
- **WHEN** a configured wake word is spoken and recognized by sherpa-onnx
- **THEN** the system plays the wake beep and opens the command listening window exactly as with Vosk

#### Scenario: Command matched after wake word
- **WHEN** a command phrase is recognized within the command timeout window
- **THEN** the corresponding trigger actions are dispatched identically to the Vosk backend
