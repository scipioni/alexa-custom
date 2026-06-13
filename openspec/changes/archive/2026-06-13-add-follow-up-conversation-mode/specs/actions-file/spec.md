## MODIFIED Requirements

### Requirement: actions.yaml schema with global and per-wake-word triggers
Each action file in `conf/actions/` SHALL support the following top-level keys:

- `triggers`: flat list of trigger entries; each trigger MAY include a `wake_words` field to declare its scope (see trigger-wake-words capability). Triggers with no `wake_words` field or `wake_words: [global]` are global fallbacks; triggers with `wake_words: []` are direct-match; triggers with named ids are scoped to those wake-word groups.
- `on_startup`: list of action entries — **only honoured in `system.yaml`; ignored in all other files**

A trigger entry MAY include an optional `follow_up` boolean field that overrides the global `recognition.follow_up` setting for that trigger (see the follow-up-conversation capability): `follow_up: true` forces a follow-up window after that command even when the global switch is off; `follow_up: false` suppresses the follow-up window even when the global switch is on; when the field is absent the trigger inherits the global setting.

The `wake_triggers` top-level key is no longer supported. The `direct_match` field on trigger entries is no longer supported.

#### Scenario: Global triggers loaded from user.yaml
- **WHEN** `conf/actions/user.yaml` contains a `triggers:` list with no `wake_words` field on entries
- **THEN** those triggers are available as global fallback for all wake word groups

#### Scenario: Per-wake-word triggers declared inline via wake_words
- **WHEN** `conf/actions/home.yaml` contains a trigger with `wake_words: [galileo]`
- **THEN** that trigger is appended to the `galileo` group's trigger list only

#### Scenario: Direct-match trigger declared via wake_words
- **WHEN** `conf/actions/user.yaml` contains a trigger with `wake_words: []`
- **THEN** that trigger is placed in `ActionsConfig.direct_triggers` and fires from stage-1 STT without a wake word

#### Scenario: Unknown wake word key in wake_triggers (removed key)
- **WHEN** any action file contains a `wake_triggers:` top-level key
- **THEN** the key is ignored with a warning log; triggers within it are not loaded

#### Scenario: Per-trigger follow_up override parsed
- **WHEN** a trigger entry sets `follow_up: false`
- **THEN** `Trigger.follow_up` is `False` and that command does not open a follow-up window even when `recognition.follow_up` is `true`

#### Scenario: Trigger without follow_up inherits global
- **WHEN** a trigger entry omits the `follow_up` field
- **THEN** `Trigger.follow_up` is `None` and follow-up behavior for that command is governed by `recognition.follow_up`
