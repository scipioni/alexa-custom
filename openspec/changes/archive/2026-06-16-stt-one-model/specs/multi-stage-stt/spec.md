## REMOVED Requirements

### Requirement: Independent STT backends for stage 1 and stage 2
**Reason**: The two-stage architecture is replaced by a single always-on transcription model (see `single-model-stt`). There is no longer a separate stage-1 and stage-2 backend.
**Migration**: Set `stt.backend` and `stt.model_path` to the values previously under `stt.stage2`. The cheap-gate stage-1 settings are dropped.

### Requirement: stt.stage1 configuration block
**Reason**: No stage-1 cheap-gate model exists in the single-model design.
**Migration**: Remove `stt.stage1` from config. Energy/VAD controls (`rms_threshold`, `adaptive_rms`, `min_speech_ms`, `vad_silence_ms`) move to the top-level `stt` block where still applicable.

### Requirement: stt.stage2 configuration block
**Reason**: Folded into the single `stt` block.
**Migration**: Move `stt.stage2.backend` → `stt.backend`, `stt.stage2.model_path` → `stt.model_path`, `stt.stage2.num_threads` → `stt.num_threads`.

### Requirement: Single-stage mode uses stage2 backend
**Reason**: `recognition.mode` (`two-stage`/`single-stage`) is removed; there is only one loop.
**Migration**: Remove `recognition.mode` from config. Behavior is now always single-model.

### Requirement: recognition.partial_matching configuration
**Reason**: Partial-transcript intent firing is removed; matches fire on endpoint (see `single-model-stt` and `streaming-intent-detection`).
**Migration**: Remove `recognition.partial_matching`, `partial_stability_ms`, and `partial_stability_reads` from config.

## MODIFIED Requirements

### Requirement: Top-level stt.vad_silence_ms for stage-2 VAD

`stt.vad_silence_ms` SHALL set the silence duration (in ms) after last speech before the single model's current utterance is finalized (the endpoint used to confirm a wake/command match). It is no longer scoped to a stage-2 capture window.

#### Scenario: Utterance finalized after silence

- **WHEN** the speaker stops for at least `stt.vad_silence_ms`
- **THEN** the single model finalizes the current utterance and the transcript is matched

### Requirement: Backend reload on config change

When the configured `stt.backend`, `stt.model_path`, wake words, or command phrases change, the worker SHALL reload the single model (or rebuild matching state) without requiring a full process restart.

#### Scenario: Backend swapped via hot-reload

- **WHEN** `stt.backend` changes in config while the daemon runs
- **THEN** the worker reloads the single model with the new backend
- **AND** resumes listening without a process restart
