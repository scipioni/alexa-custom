# Capability: Trigger Wake Words

## Purpose
Declare per-trigger wake word scoping so a single flat trigger list can target any runtime slot (direct-match, global, or per-group).

## Requirements

### Requirement: wake_words field on trigger entries
Each trigger entry in an action file MAY include a `wake_words` field (list of strings). The system SHALL resolve this field at parse time to determine which runtime slot the trigger occupies:

- Field absent or list containing `"global"` → trigger is active after any wake word (global slot).
- Empty list (`[]`) → trigger fires directly from stage-1 STT without a wake word (direct-match slot).
- List of one or more wake-word group IDs → trigger is appended to each named group's trigger list.

The `wake_words` field SHALL NOT be present on the resolved `Trigger` object at runtime; resolution is a parse-time concern.

#### Scenario: Trigger with no wake_words is global
- **WHEN** an action file defines a trigger with no `wake_words` field
- **THEN** that trigger is available after any wake word fires, identical to the previous global `triggers:` behaviour

#### Scenario: Trigger with wake_words: [global] is global
- **WHEN** an action file defines a trigger with `wake_words: [global]`
- **THEN** that trigger is available after any wake word fires

#### Scenario: Trigger with wake_words: [] is a direct-match trigger
- **WHEN** an action file defines a trigger with `wake_words: []`
- **THEN** that trigger is placed in `ActionsConfig.direct_triggers` and evaluated by stage-1 STT without requiring a wake word

#### Scenario: Trigger scoped to a single wake-word group
- **WHEN** an action file defines a trigger with `wake_words: [help]` and a wake-word group with `id: help` exists
- **THEN** that trigger is appended to the `help` group's trigger list only

#### Scenario: Trigger scoped to multiple wake-word groups
- **WHEN** an action file defines a trigger with `wake_words: [galileo, help]`
- **THEN** that trigger is appended to both the `galileo` group's and the `help` group's trigger lists

#### Scenario: Unknown wake-word id in wake_words
- **WHEN** a trigger's `wake_words` contains an id that does not match any configured wake-word group
- **THEN** that id is silently ignored with a debug log; the trigger is still resolved using any valid ids in the list

### Requirement: ActionsConfig carries direct_triggers list
`ActionsConfig` SHALL expose a `direct_triggers: list[Trigger]` field containing all triggers resolved to the direct-match slot.

#### Scenario: direct_triggers populated at load time
- **WHEN** config is loaded and one trigger has `wake_words: []`
- **THEN** `ActionsConfig.direct_triggers` contains that trigger and `ActionsConfig.triggers` does not
