## MODIFIED Requirements

### Requirement: Config-driven trigger-to-action mapping
The system SHALL load trigger phrases and action sequences from `config.yaml` and action files in `conf/actions/`. Each trigger entry defines a `phrase` (matched against STT output) and a list of `actions` to execute sequentially.

Triggers are resolved at load time into three slots:
- **Direct triggers** (`ActionsConfig.direct_triggers`): evaluated by stage-1 STT without a wake word.
- **Global triggers** (`ActionsConfig.triggers`): evaluated after any wake word fires.
- **Group triggers** (`WakeWordGroup.triggers`): evaluated after the specific wake word for that group fires.

Inline `triggers:` defined under a `wake_words:` group entry in `config.yaml` continue to be scoped to that group without requiring a `wake_words` field.

All recognized phrases SHALL be published to MQTT for external processing. The active trigger list SHALL be updated without process restart when config files change on disk.

#### Scenario: Single action on phrase match
- **WHEN** the recognized command matches a configured trigger phrase
- **THEN** all actions in that trigger's `actions` list are executed in order

#### Scenario: Multiple actions on one phrase
- **WHEN** a trigger defines two actions (e.g., telegram + livekit_join)
- **THEN** both actions execute sequentially in the listed order

#### Scenario: No config file present
- **WHEN** neither `config.yaml` nor any action file exists at startup
- **THEN** the process behaves as before (auto-connect to LiveKit, no wake word detection)

#### Scenario: Trigger list updated after hot reload of actions file
- **WHEN** a new trigger phrase is added to an action file and the file is saved
- **THEN** the next recognized command is matched against the updated trigger list

#### Scenario: Unmatched command with LLM fallback enabled
- **WHEN** no trigger matches the transcription and `llm.fallback_on_no_match` is `true`
- **THEN** the transcript is routed to the `ConversationEngine` instead of playing the timeout tone

#### Scenario: Unmatched command with LLM not configured
- **WHEN** no trigger matches and `llm:` is absent from `config.yaml`
- **THEN** the timeout tone plays as before

#### Scenario: Direct-match trigger fires without wake word
- **WHEN** stage-1 STT recognizes a phrase that matches a trigger in `ActionsConfig.direct_triggers`
- **THEN** that trigger's actions execute immediately without waiting for a wake word

#### Scenario: Direct-match trigger no longer uses direct_match flag
- **WHEN** a trigger is configured with `wake_words: []` instead of `direct_match: true`
- **THEN** it is placed in `ActionsConfig.direct_triggers` and behaves identically to the previous `direct_match: true` behaviour
