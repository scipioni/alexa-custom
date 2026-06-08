## MODIFIED Requirements

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
