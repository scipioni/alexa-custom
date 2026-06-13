# Capability: sherpa-onnx-stt

## MODIFIED Requirements

### Requirement: Model download
The system SHALL download the sherpa-onnx NeMo FastConformer CTC model via `alexa-setup --sherpa-onnx` and store it under `models/sherpa-onnx/nemo-ctc-it/`.

#### Scenario: Model download
- **WHEN** the user runs `alexa-setup --sherpa-onnx`
- **THEN** the NeMo CTC ONNX model and tokens are downloaded to `models/sherpa-onnx/nemo-ctc-it/`

#### Scenario: Missing model at startup
- **WHEN** `stt.backend: sherpa-onnx` or `stt.stage<N>.backend: nemo-offline` is configured but the model is not present
- **THEN** the system logs an error with guidance to run `alexa-setup --sherpa-onnx` and exits with a non-zero status

## REMOVED Requirements

### Requirement: Equivalent recognition behavior
**Reason**: Offline backends (nemo-offline) do not produce streaming partial results, making streaming equivalence inapplicable. Each backend has its own recognition behavior.
**Migration**: Test each backend independently.

### Requirement: Partial results during speech
**Reason**: Offline backends transcribe after the utterance is complete; partial results are not available.
**Migration**: Use backend.partial_text() which returns "" for offline backends.
