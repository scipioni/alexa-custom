## MODIFIED Requirements

### Requirement: actions.yaml schema with global and per-wake-word triggers
Each action file in `conf/actions/` SHALL support the following top-level keys:

- `triggers`: flat list of trigger entries; each trigger MAY include a `wake_words` field to declare its scope (see trigger-wake-words capability). Triggers with no `wake_words` field or `wake_words: [global]` are global fallbacks; triggers with `wake_words: []` are direct-match; triggers with named ids are scoped to those wake-word groups.
- `on_startup`: list of action entries — **only honoured in `system.yaml`; ignored in all other files**

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

## REMOVED Requirements

### Requirement: direct_match flag on trigger entries
**Reason**: Replaced by `wake_words: []` semantics. The `direct_match: true` flag was a per-trigger boolean that caused stage-1 firing; `wake_words: []` is the canonical replacement.
**Migration**: Replace `direct_match: true` on a trigger with `wake_words: []`. Remove the `direct_match` key entirely from all trigger entries.
