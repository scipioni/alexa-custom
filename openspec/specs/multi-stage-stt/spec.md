# Capability: Multi-Stage STT

## Purpose
Support independent, pre-loaded Speech-to-Text backends for wake-word detection (stage 1) and command recognition (stage 2).

## Requirements

### Requirement: Independent STT backends for stage 1 and stage 2
The system SHALL load two independent STT backend instances at startup: one for stage 1 (continuous wake-word detection) and one for stage 2 (command recognition after wake). Each backend is configured independently via `stt.stage1` and `stt.stage2` in `conf/config.yaml`.

#### Scenario: Different backends for each stage
- **WHEN** `stt.stage1.backend: vosk` and `stt.stage2.backend: sherpa-onnx` are configured
- **THEN** wake-word detection uses the Vosk grammar-constrained recogniser and command capture uses the sherpa-onnx open-vocabulary model

#### Scenario: Same backend for both stages
- **WHEN** both `stt.stage1.backend` and `stt.stage2.backend` are `vosk`
- **THEN** two independent Vosk recogniser instances are created, one per stage

#### Scenario: Both models loaded at startup
- **WHEN** the daemon starts with stage1=vosk and stage2=sherpa-onnx
- **THEN** both models are loaded and warm before the first wake event (no on-demand load delay)

### Requirement: stt.stage1 configuration block
The `stt.stage1` block in `conf/config.yaml` SHALL accept:

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | str | `"vosk"` | `"vosk"` or `"sherpa-onnx"` |
| `model_path` | str|null | `"models/it"` | Path to model directory |
| `confidence` | float | `0.65` | Vosk word confidence threshold (ignored for sherpa-onnx) |
| `vad_silence_ms` | int | `500` | Silence duration (ms) triggering stage-1 finalization (sherpa energy VAD) |
| `rms_threshold` | float | `0.02` | Minimum RMS to count as speech in stage-1 energy VAD |
| `min_speech_ms` | int | `300` | Minimum sustained speech before silence timer can fire |

#### Scenario: Stage 1 confidence threshold applied
- **WHEN** `stt.stage1.confidence: 0.8` is set and Vosk returns a wake word with confidence 0.75
- **THEN** the wake word is NOT accepted and the system stays in stage 1

#### Scenario: Stage 1 confidence threshold met
- **WHEN** `stt.stage1.confidence: 0.65` is set and Vosk returns confidence 0.70
- **THEN** the wake word IS accepted and the system transitions to stage 2

### Requirement: stt.stage2 configuration block
The `stt.stage2` block in `conf/config.yaml` SHALL accept:

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | str | `"vosk"` | `"vosk"` or `"sherpa-onnx"` |
| `model_path` | str|null | `null` | Path to model directory; defaults to backend's default path |

#### Scenario: Stage 2 uses sherpa-onnx with custom model path
- **WHEN** `stt.stage2.backend: sherpa-onnx` and `stt.stage2.model_path: models/it/kroko_128l`
- **THEN** command capture uses the sherpa-onnx model at that path

### Requirement: Top-level stt.vad_silence_ms for stage-2 VAD
The `stt.vad_silence_ms` field at the top of the `stt:` block SHALL control the silence duration used by `capture_transcript` (stage 2 command window). This is distinct from `stt.stage1.vad_silence_ms` which controls stage-1 energy VAD.

#### Scenario: Stage 2 VAD silence tuned separately from stage 1
- **WHEN** `stt.vad_silence_ms: 1000` and `stt.stage1.vad_silence_ms: 400` are configured
- **THEN** command capture waits 1000 ms of silence before finalising, while stage-1 fires after 400 ms

### Requirement: Single-stage mode uses stage2 backend
When `recognition.mode: single-stage`, the system SHALL use the `stage2` backend for the single combined wake+command pipeline.

#### Scenario: Single-stage mode backend selection
- **WHEN** `recognition.mode: single-stage` and `stt.stage2.backend: sherpa-onnx`
- **THEN** the single-stage loop uses the sherpa-onnx backend throughout

### Requirement: Backend reload on config change
When either `stt.stage1` or `stt.stage2` configuration changes during hot-reload, the system SHALL reload the affected backend(s) on the next capture-process restart.

#### Scenario: Stage 2 model path changed via hot-reload
- **WHEN** `stt.stage2.model_path` is changed in `conf/config.yaml` and the file is saved
- **THEN** the stage-2 backend is reloaded with the new model path on the next STT loop iteration
