## ADDED Requirements

### Requirement: CLI entry point for model-aware calibration
The system SHALL provide an `alexa-mic-calibrate` CLI command that performs fully automatic model-aware microphone gain calibration.

#### Scenario: Command exists and is discoverable
- **WHEN** user runs `alexa-mic-calibrate --help`
- **THEN** system SHALL print usage information showing the command is available

#### Scenario: Dry-run mode
- **WHEN** user runs `alexa-mic-calibrate --dry-run`
- **THEN** system SHALL run the full calibration and print results but NOT write the gain to `config.yaml`

### Requirement: Test phrase WAV
The system SHALL ship a pre-recorded 16-bit 16kHz mono WAV file at `models/test_phrase.wav` containing a human Italian voice saying the test phrase.

#### Scenario: WAV file exists
- **WHEN** the calibrator starts
- **THEN** the WAV file SHALL be loadable and valid

#### Scenario: WAV is scaled for distance simulation
- **WHEN** the calibrator prepares test signals for a distance volume level
- **THEN** the system SHALL create a scaled copy of the WAV at the target volume using `_scale_wav_to_playback_volume()`

### Requirement: Gain sweep with model-aware scoring
The system SHALL sweep through multiple input gain levels and score each by actual STT transcription accuracy.

#### Scenario: Full sweep at middle distance
- **WHEN** calibrator starts the coarse phase
- **THEN** it SHALL test all gains in `TEST_GAINS` at the `medio` distance volume (0.30)
- **AND** for each gain, it SHALL:
  - Set the input gain via `set_input_gain()`
  - Play the scaled speech WAV via `pw-play`
  - Capture the audio via `parec`
  - Transcribe the captured audio with the configured `stt.stage2` backend
  - Compute `get_similarity_score(expected, actual, "token_set_ratio")`
  - Apply a clipping penalty if >1% of frames are clipped

#### Scenario: Selective test at near and far distance
- **WHEN** coarse phase completes
- **THEN** the top 2 gains SHALL be tested at `vicino` (0.80) and `lontano` (0.06) volume levels

#### Scenario: Refinement pass around winner
- **WHEN** selective phase completes and a winning gain is identified
- **THEN** the system SHALL sweep gains at ±0.4 range with 0.1 step around the winner at `lontano` volume only
- **AND** replace the winner if a fine-grained gain yields higher far-field SNR

#### Scenario: Confirmation pass
- **WHEN** refinement completes
- **THEN** the winning gain SHALL be re-tested at `medio` volume
- **AND** if the re-test score deviates >20% from the original measurement, a second confirmation test SHALL run
- **AND** if the second also deviates, the system SHALL fall back to gain 1.0

### Requirement: Weighted scoring across distances
The system SHALL compute a weighted average score to select the best gain.

#### Scenario: Far-field weighted higher
- **WHEN** computing the combined score for a gain across distances
- **THEN** `lontano` SHALL be weighted 5×, `medio` 2×, `vicino` 1× (matching existing `_AUTO_PLAY_VOLUMES` weights)

### Requirement: Persist selected gain
The system SHALL write the winning gain to `config.yaml` under `audio.input_gain`.

#### Scenario: Gain saved to config
- **WHEN** calibration completes without `--dry-run`
- **THEN** system SHALL write `audio.input_gain: <winner>` to `conf/config.yaml` using `_save_gain_to_config()`

#### Scenario: Existing config preserved
- **WHEN** saving the gain
- **THEN** comments and other keys in `config.yaml` SHALL be preserved (ruamel.yaml atomic write)

### Requirement: STT backend agnostic
The calibration SHALL work with any STT backend configured in `stt.stage2`.

#### Scenario: Works with Vosk
- **WHEN** `stt.stage2.backend` is `vosk`
- **THEN** calibration SHALL use the Vosk model for transcription scoring

#### Scenario: Works with sherpa-onnx
- **WHEN** `stt.stage2.backend` is `sherpa-onnx`
- **THEN** calibration SHALL use the sherpa-onnx model for transcription scoring

#### Scenario: Works with whisper-cpp
- **WHEN** `stt.stage2.backend` is `whisper-cpp`
- **THEN** calibration SHALL use the whisper-cpp model for transcription scoring

#### Scenario: Works with nemo-offline
- **WHEN** `stt.stage2.backend` is `nemo-offline`
- **THEN** calibration SHALL use the nemo-offline model for transcription scoring

### Requirement: Summary output
The system SHALL print a summary table of results after calibration.

#### Scenario: Results table printed
- **WHEN** calibration completes
- **THEN** system SHALL print a table with gains as rows, distances as columns, scores as cells, and a marker for the winner
