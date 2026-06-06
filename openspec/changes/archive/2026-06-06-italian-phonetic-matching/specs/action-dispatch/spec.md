## MODIFIED Requirements

### Requirement: Fuzzy phrase matching
The system SHALL match the STT transcription against configured trigger phrases using `rapidfuzz.fuzz.token_set_ratio` applied to phonetically-normalized strings (via `italian_phonetic()`), with a configurable similarity threshold (default 70, on a 0–100 scale). The trigger with the highest score above the threshold is selected. If `rapidfuzz` is unavailable, the system SHALL fall back to `difflib.SequenceMatcher` with a threshold of 0.70 and log a warning.

#### Scenario: Exact phrase match
- **WHEN** the transcription exactly matches a trigger phrase
- **THEN** that trigger is selected

#### Scenario: Inflected phrase match
- **WHEN** the transcription is `"chiamare"` and the trigger phrase is `"chiama"`
- **THEN** the trigger is selected if similarity exceeds the threshold

#### Scenario: No phrase meets threshold
- **WHEN** the transcription similarity to all trigger phrases is below 70
- **THEN** no action is dispatched and the system plays the timeout beep

#### Scenario: Extra words around trigger phrase
- **WHEN** the transcription is `"mi chiama subito"` and the trigger phrase is `"chiama"`
- **THEN** the trigger is selected (token_set_ratio scores the overlap regardless of surrounding tokens)

#### Scenario: Phonetic variant of trigger phrase
- **WHEN** the transcription is `"ke fai"` and the trigger phrase is `"che fai"`
- **THEN** after phonetic normalization both sides compare as `"ke fai"` and the trigger is selected
