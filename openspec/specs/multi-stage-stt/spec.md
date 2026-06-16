# Capability: Multi-Stage STT

## Purpose
Support independent, pre-loaded Speech-to-Text backends for wake-word detection (stage 1) and command recognition (stage 2).

## Requirements

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
