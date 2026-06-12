## ADDED Requirements

### Requirement: Pink noise generation seeded for reproducibility
The system SHALL seed `np.random` with value `42` at the start of `_generate_pink_noise()` to produce deterministic pink noise waveforms across calibration runs.

#### Scenario: Identical pink noise on repeated calls
- **WHEN** `_generate_pink_noise()` is called twice with the same duration and samplerate
- **THEN** both calls SHALL return identical sample arrays

### Requirement: Robust noise floor via median of multiple measurements
The system SHALL capture 3 noise floor measurements of 0.3 seconds each with 0.1s inter-measurement gaps, compute RMS per channel for each, and take the median RMS value across the 3 captures.

#### Scenario: Single transient spike ignored
- **WHEN** one of the 3 captures contains a transient noise spike (e.g., door slam)
- **THEN** the median RMS SHALL reflect the quieter captures, ignoring the spike

### Requirement: Channel balance penalty in gain selection
The system SHALL compute channel balance as the absolute dB ratio between the RMS of the two loudest channels. When imbalance exceeds 6 dB, the `weighted_snr` SHALL be multiplied by 0.5 before candidate ranking.

#### Scenario: Unbalanced gain penalized
- **WHEN** two candidate gains have identical weighted SNR
- **AND** one has channel imbalance < 6dB, the other > 6dB
- **THEN** the balanced gain SHALL be selected

### Requirement: Frequency-weighted SNR
The system SHALL compute SNR per frequency band using FFT: low band (0–300 Hz) weight 0.5, speech band (300–3400 Hz) weight 2.0, high band (3400+ Hz) weight 0.5. The weighted SNR SHALL replace the current broadband SNR in all selection criteria.

#### Scenario: Speech-band noise penalized less
- **WHEN** noise is concentrated in low frequencies (e.g., fan hum below 300 Hz)
- **THEN** the weighted SNR SHALL be higher than broadband SNR because the low band weight is 0.5

### Requirement: Multi-volume refinement pass
After coarse selection, the refinement pass SHALL test fine-grained gains (0.1 step within ±0.4 of winner) at all 3 playback volumes ("lontano", "medio", "vicino"). Each fine candidate SHALL receive a weighted SNR using the same 5:2:1 weight ratio as the coarse pass.

#### Scenario: Refinement at all volumes
- **WHEN** the refinement pass runs for a candidate gain
- **THEN** captures SHALL be performed at "lontano" (5%), "medio" (30%), and "vicino" (80%) playback volumes
- **AND** a weighted SNR SHALL be computed across all three

### Requirement: STT validation pass after acoustic selection
After the refinement pass selects a winner, the system SHALL synthesize `_SPEECH_TEST_PHRASE` via Piper TTS, play it at "lontano" volume, capture, transcribe via the active STT backend, and compute `get_similarity_score(transcript, phrase, "token_set_ratio")`.

#### Scenario: STT score below threshold
- **WHEN** the STT validation score is below 50%
- **THEN** the system SHALL reject the current candidate and test the next-best gain
- **AND** if all candidates are rejected, the system SHALL keep the original acoustic winner

#### Scenario: STT score passes
- **WHEN** the STT validation score is ≥ 50%
- **THEN** the current candidate SHALL be confirmed as the final winner

### Requirement: Non-punitive confirmation fallback
The confirmation pass SHALL retry up to 3 times if the SNR deviation exceeds 20%. If all retries fail, the system SHALL fall back to the coarse winner (before refinement) instead of hardcoded gain 1.0.

#### Scenario: Confirmation retries on deviation
- **WHEN** the first confirmation measurement deviates >20% from the coarse measurement
- **THEN** the system SHALL re-measure up to 2 additional times
- **AND** select the median of the 3 measurements for comparison

#### Scenario: All retries fail
- **WHEN** all 3 confirmation attempts deviate >20%
- **THEN** the system SHALL fall back to the coarse winner (pre-refinement)
