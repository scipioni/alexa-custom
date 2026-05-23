## MODIFIED Requirements

### Requirement: Configurable wake word list
The system SHALL load wake words from the `wake_words` list in `config.yaml`. Each entry SHALL be a wake word group object with a required `word` field (the primary recognition phrase), an optional `aliases` list (additional recognition phrases that map to the same group), and an optional `triggers` list (commands active after this wake word fires). At least one wake word group MUST be defined. Duplicate aliases across groups SHALL cause a warning to be logged at parse time; the first group defining the alias takes precedence.

#### Scenario: Multiple wake word groups configured
- **WHEN** `wake_words` contains two groups with different `word` values
- **THEN** either spoken word triggers command listening mode, each using its own trigger list

#### Scenario: Wake word with aliases
- **WHEN** a group defines `word: galileo` and `aliases: [hey galileo]`
- **THEN** speaking either "galileo" or "hey galileo" activates that group's command window

#### Scenario: Missing wake word list
- **WHEN** `config.yaml` is present but `wake_words` is empty or absent
- **THEN** the system logs an error and exits with a non-zero status

#### Scenario: Duplicate alias warning
- **WHEN** two groups define the same alias string
- **THEN** a warning is logged at config parse time and the first group's mapping is used

### Requirement: Command recognition window
After wake word detection, the system SHALL open a full-transcription recognition window of configurable duration (default 3 seconds). The system SHALL use the trigger list of the matched wake word group for command matching. If the matched group defines no triggers, the system SHALL fall back to the global top-level `triggers` list. If a command is recognized within the window it is dispatched to the action system and published to MQTT. If the window expires without a match, the system plays a timeout beep and returns to Stage 1.

#### Scenario: Command matched using group triggers
- **WHEN** wake word group "galileo" has its own triggers and the user speaks a phrase matching one of them
- **THEN** the corresponding actions are dispatched using the group's trigger list

#### Scenario: Command matched using global fallback triggers
- **WHEN** wake word group "assistente" has no triggers defined and the user speaks a phrase matching a global trigger
- **THEN** the corresponding actions are dispatched using the global fallback trigger list

#### Scenario: Command window timeout
- **WHEN** no speech or no matching phrase is detected within `command_timeout` seconds
- **THEN** the system plays a timeout beep and resumes wake word listening

#### Scenario: No triggers anywhere
- **WHEN** a wake word group has no triggers and the global triggers list is also empty
- **THEN** the command window opens, nothing matches, the timeout beep plays, and the system returns to Stage 1
