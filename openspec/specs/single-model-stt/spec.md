# Capability: Single Model STT

## Purpose
Run a single always-on transcription model for both wake-word and command recognition, replacing the prior two-stage (cheap-gate + capture) architecture.

## Requirements

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

The single model's backend SHALL be configurable via `stt.backend`, accepting `vosk` or `sherpa-onnx`. Backend-specific options (e.g. `model_path`, `num_threads`) SHALL be configurable under `stt`. The `sherpa-onnx` backend SHALL additionally accept `stt.sherpa_vad_threshold`, `stt.sherpa_vad_min_speech_ms`, and `stt.sherpa_vad_min_silence_ms` to tune its internal Silero VAD gate; these SHALL have no effect when `stt.backend` is `vosk`. None of these new fields SHALL be part of the backend-reload key (`_get_backend_key`) — changing them takes effect on the next natural backend reconstruction (e.g. a `model_path`/`num_threads` change or daemon restart), not immediately via hot-reload, to avoid an expensive reload (see Requirement below) on every minor tuning tweak.

#### Scenario: Vosk backend selected

- **WHEN** `stt.backend` is `vosk`
- **THEN** the worker loads a Vosk free-vocabulary recognizer as the single model

#### Scenario: Sherpa-onnx backend selected

- **WHEN** `stt.backend` is `sherpa-onnx`
- **THEN** the worker loads a Kroko Zipformer streaming recognizer (via sherpa-onnx) as the single model, using `stt.model_path` as the model directory
- **AND** the recognizer is gated by an internal Silero VAD instance that skips feeding audio to the encoder while no speech is detected

#### Scenario: Sherpa-onnx dependency missing

- **WHEN** `stt.backend` is `sherpa-onnx`
- **AND** the `sherpa-onnx` package is not installed
- **THEN** backend construction raises a clear, actionable error naming the install command
- **AND** this failure is distinct from a `ConfigError` (it is an environment/dependency issue, not an invalid config value)

#### Scenario: Invalid backend rejected

- **WHEN** `stt.backend` is not a supported value
- **THEN** config loading raises a `ConfigError` naming the offending value

### Requirement: Backend reload cost is bounded to actual backend-affecting changes

Reconstructing the `sherpa-onnx` backend is expensive (~40-50s model load, measured on this board's hardware — a prior sherpa-onnx integration was removed from this project in part for this reason; see `docs/asr-plan.md` and git history `657f57c`/`b5a2412`). The system SHALL NOT reconstruct the STT backend in response to config changes that don't affect backend identity — only `stt.backend`, `stt.model_path`, `stt.num_threads`, `stt.vosk_grammar`, or the computed wake/command grammar SHALL trigger a reload, matching the existing `_get_backend_key` mechanism already used for `vosk`.

#### Scenario: Unrelated config change does not reload the backend

- **WHEN** `stt.backend` is `sherpa-onnx`
- **AND** a config value outside `_get_backend_key`'s fields changes (e.g. a wake word, volume, or `stt.sherpa_vad_threshold`)
- **THEN** the hot-reload loop does NOT reconstruct the backend
- **AND** the ~40-50s reload cost is not incurred

#### Scenario: Backend-affecting change does reload the backend

- **WHEN** `stt.backend`, `stt.model_path`, or `stt.num_threads` changes
- **THEN** the hot-reload loop reconstructs the backend, incurring the model's real load time
- **AND** this is logged (matching the existing "STT backend reloaded (%.1fs) after config change" log line)

### Requirement: Backend model provisioning via serena-setup

`serena-setup` SHALL be able to provision the model files required by the `sherpa-onnx` backend (a Kroko Zipformer model directory and `silero_vad.onnx`), in addition to its existing Vosk/Piper provisioning, without altering default behavior when invoked with no sherpa-onnx-specific flags.

#### Scenario: Kroko model download

- **WHEN** `serena-setup` is invoked with the sherpa-onnx model download option
- **THEN** it downloads and unpacks the requested Kroko model variant (`kroko_64l` by default) into `models/it/`

#### Scenario: Silero VAD model download

- **WHEN** `serena-setup` is invoked with the sherpa-onnx model download option
- **THEN** it downloads `silero_vad.onnx` into `models/vad/` if not already present

#### Scenario: Default setup run unaffected

- **WHEN** `serena-setup` is invoked with no arguments (existing default behavior)
- **THEN** it downloads Vosk and Piper assets exactly as before
- **AND** it does not download sherpa-onnx/Kroko assets unless explicitly requested

### Requirement: Endpoint-gated matching with confirmation tone

The system SHALL act on a matched wake word or command only once the utterance is followed by silence (a VAD/endpoint event). On a confirmed match the system SHALL start playback of a "good tone" without blocking the recognition loop: tone playback and action dispatch SHALL proceed concurrently, and the recognition thread SHALL NOT wait for tone playback to finish before dispatching.

#### Scenario: Match confirmed on silence

- **WHEN** the transcript matches a wake word or command phrase
- **AND** the speaker stops (silence ≥ `stt.vad_silence_ms`) or the backend reports an endpoint
- **THEN** the system starts playback of the configured good tone
- **AND** proceeds to dispatch / wake-state handling without waiting for the tone to finish

#### Scenario: No tone before silence

- **WHEN** a partial transcript matches but speech is ongoing
- **THEN** no tone is emitted and no dispatch occurs until the endpoint

#### Scenario: Tone disabled

- **WHEN** `recognition.wake_tone` is `none`
- **THEN** no tone playback process is started
- **AND** dispatch proceeds immediately, identical to today's behavior

#### Scenario: Beep echo does not re-trigger recognition

- **WHEN** the good tone is playing while the microphone is capturing
- **THEN** the tone's acoustic echo is absorbed by the existing post-wake flush (`stt.flush_ms`) / playback-gate mechanisms
- **AND** the tone does not produce a transcript that matches a wake word or trigger

### Requirement: Single recognition loop

The worker SHALL implement recognition in a single transcribe→match→gate→tone→dispatch loop, without `recognition.mode` branching or separate per-backend (`is_kws`/`is_vosk`/`else`) firing paths.

#### Scenario: Backend differences hidden behind one interface

- **WHEN** any supported backend is configured
- **THEN** the same loop drives it via a common transcript/endpoint interface
- **AND** there is no `two-stage` vs `single-stage` mode selector
