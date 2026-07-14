## ADDED Requirements

### Requirement: Confuser phrases expand stage-1 grammar
The system SHALL add confuser phrases to the Vosk stage-1 grammar vocabulary alongside wake-word phrases. Confuser phrases SHALL be included in the grammar so Vosk can produce them as output, but SHALL NOT be added to the alias map and SHALL NOT trigger command mode. When a stage-1 result matches a confuser phrase the recogniser SHALL be reset silently without playing any audio cue.

#### Scenario: Single wake word component rejected
- **WHEN** the wake word is configured as `"aiuto aiuto"` and the user (or TV) says `"aiuto"` once
- **THEN** Vosk outputs `"aiuto"` (present in grammar as confuser), the system resets stage-1 silently, and command mode is NOT entered

#### Scenario: Full wake phrase still triggers
- **WHEN** the wake word is `"aiuto aiuto"` and the user says `"aiuto aiuto"`
- **THEN** the system detects the wake word normally and enters command mode

#### Scenario: Manual confuser rejected
- **WHEN** `confusers: ["arduino"]` is set on a wake-word group and the user says `"arduino"`
- **THEN** Vosk outputs `"arduino"`, the system resets stage-1 silently, and command mode is NOT entered

### Requirement: Automatic sub-phrase confuser derivation
When `auto_confusers` is `true` (default), the system SHALL automatically derive confuser phrases from the configured wake words and aliases by splitting each multi-word phrase into its component tokens. Any component token that does not itself appear as a standalone wake word or alias in any group SHALL be added to the confuser set. Single-word wake words do not produce sub-phrase confusers.

#### Scenario: Multi-word wake phrase produces sub-phrase confusers
- **WHEN** `wake_words: [{word: "aiuto aiuto"}]` is configured
- **THEN** `"aiuto"` is automatically added as a confuser

#### Scenario: Alias component also produces confuser
- **WHEN** `aliases: ["mi serve aiuto"]` is configured and `"mi"`, `"serve"`, `"aiuto"` are not standalone wake words
- **THEN** all three tokens are added as confusers

#### Scenario: Token already a wake word is not made a confuser
- **WHEN** both `"aiuto"` and `"aiuto aiuto"` are configured as separate wake words
- **THEN** `"aiuto"` is NOT added as a confuser (it is a standalone trigger)

#### Scenario: auto_confusers disabled
- **WHEN** `auto_confusers: false` is set under `stt.stage1`
- **THEN** no confusers are derived automatically; only the manual `confusers` list is used; grammar contains only wake-word phrases and aliases

### Requirement: Automatic phonetic confuser derivation
When `auto_confusers` is `true`, the system SHALL compute phonetic confusers by comparing each wake word and alias against a bundled Italian word corpus using IPA phoneme edit distance (via `espeak-ng`). Words whose IPA distance from any wake phrase is ≤ `confuser_distance` (default 3) SHALL be added to the confuser set. The total number of automatically derived confusers (sub-phrase + phonetic combined) SHALL NOT exceed `max_confusers` (default 30); if the limit is reached the closest-distance words are preferred and a DEBUG-level log message is emitted.

#### Scenario: Phonetically close word added as confuser
- **WHEN** wake word is `"galileo"` and `confuser_distance: 3`
- **THEN** Italian words within IPA edit distance 3 of `"galileo"` (e.g. `"galilei"`, `"calibro"`) are added as confusers

#### Scenario: espeak-ng unavailable
- **WHEN** the `espeak-ng` binary is not found on the system
- **THEN** a WARNING is logged, phonetic confusers are skipped, and sub-phrase confusers and manual confusers are still applied

#### Scenario: confuser_distance zero disables phonetic confusers
- **WHEN** `confuser_distance: 0` is set
- **THEN** no phonetic confusers are derived; only sub-phrase and manual confusers apply

#### Scenario: max_confusers cap respected
- **WHEN** phonetic distance would produce more confusers than `max_confusers`
- **THEN** only the closest-distance words are kept up to the cap, and a DEBUG message lists the dropped words

### Requirement: Confuser computation at config load
The system SHALL compute confusers once at config load time (including hot-reloads). Confuser computation SHALL NOT run on every audio chunk. The computed confuser set SHALL be logged at DEBUG level showing source (sub-phrase / phonetic / manual) and total count.

#### Scenario: Confusers recomputed on hot-reload
- **WHEN** `config.yaml` is modified and the daemon hot-reloads it
- **THEN** the confuser set and stage-1 grammar are recomputed with the new configuration

#### Scenario: Confuser set logged at startup
- **WHEN** the daemon starts and loads configuration
- **THEN** a DEBUG log line lists all confuser phrases and their source (sub-phrase / phonetic / manual)
