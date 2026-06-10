# Capability: Voice Volume Control

## Purpose
Parse Italian voice commands containing volume percentages and adjust the system output volume accordingly.

## ADDED Requirements

### Requirement: Percentage extraction from transcript
The system SHALL parse a volume percentage value from the raw STT transcript. The parser SHALL handle both digit-based ("80%", "50 %", "80 per cento") and Italian number word forms ("ottanta per cento", "cinquanta", "settantacinque"). The extracted value SHALL be clamped to the range 0–100 before conversion to a 0.0–1.0 float.

#### Scenario: Digit percentage with percent sign
- **WHEN** the transcript contains "80%"
- **THEN** the system extracts 80 and converts to 0.80

#### Scenario: Digit percentage with "per cento"
- **WHEN** the transcript contains "50 per cento"
- **THEN** the system extracts 50 and converts to 0.50

#### Scenario: Italian number word
- **WHEN** the transcript contains "ottanta"
- **THEN** the system extracts 80 and converts to 0.80

#### Scenario: Italian compound number word
- **WHEN** the transcript contains "venticinque"
- **THEN** the system extracts 25 and converts to 0.25

#### Scenario: Value out of range clamped
- **WHEN** the transcript contains "cento cinquanta per cento"
- **THEN** the system extracts 150 but clamps to 100 (converts to 1.0)

#### Scenario: No number in transcript
- **WHEN** the transcript contains "alza il volume" with no numeric value
- **THEN** the system returns None and does not adjust volume

### Requirement: Trigger phrase routing
The system SHALL define a trigger phrase "volume al" (with aliases "imposta volume a", "metti volume a", "volume") in the action file that routes to the `set_volume_from_transcript` action type. The trigger SHALL use the existing fuzzy phonetic matching system.

#### Scenario: Trigger matched by "volume al 80%"
- **WHEN** the transcript is "volume al 80%"
- **THEN** the fuzzy matcher selects the "volume al" trigger and dispatches `set_volume_from_transcript`

#### Scenario: Trigger matched by alias "metti volume a 50"
- **WHEN** the transcript is "metti volume a 50"
- **THEN** the fuzzy matcher selects the trigger via alias and dispatches `set_volume_from_transcript`

### Requirement: Italian number word parser
The system SHALL convert Italian number words (0–100) to integers. The parser SHALL handle: zero, units (uno–nove), tens (dieci–novanta), compounds (ventuno–novantanove), and "cento". The parser SHALL be case-insensitive and SHALL strip diacritics.

#### Scenario: Simple unit word
- **WHEN** the word is "cinque"
- **THEN** the parser returns 5

#### Scenario: Ten word
- **WHEN** the word is "trenta"
- **THEN** the parser returns 30

#### Scenario: Compound word (tens + unit)
- **WHEN** the word is "ventidue"
- **THEN** the parser returns 22

#### Scenario: "cento" handled
- **WHEN** the word is "cento"
- **THEN** the parser returns 100

### Requirement: Volume change confirmation
After setting the volume via voice command, the system SHALL play a brief confirmation tone and optionally announce the new volume level via TTS.

#### Scenario: Confirmation after volume set
- **WHEN** the volume is successfully changed to 80%
- **THEN** the system plays a confirmation tone
