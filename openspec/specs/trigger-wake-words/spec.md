# Capability: Trigger Wake Words

## Purpose
Declare per-trigger wake word scoping so a single flat trigger list can target any runtime slot (direct-match or wake-gated).

## Requirements

### Requirement: wake_words field on trigger entries

Trigger entries SHALL express their wake requirement through a boolean `with_wake` field instead of the previous `wake_words: None | [] | [ids]` taxonomy. `with_wake: false` means the command fires with no wake word (formerly *direct*). `with_wake: true` (the default) means the command fires only when a wake word was recently detected (formerly *global*). Per-wake-word *scoping* (binding a command to a specific wake group) is no longer expressed on the trigger.

#### Scenario: Direct trigger via with_wake false

- **WHEN** a trigger sets `with_wake: false`
- **THEN** its commands fire on match regardless of wake state

#### Scenario: Wake-gated trigger via with_wake true

- **WHEN** a trigger sets `with_wake: true` or omits the field
- **THEN** its commands fire only when a wake word is currently active

### Requirement: wake_words is a flat list of phrases

`wake_words` SHALL be configured as a flat list of phrase strings. Any configured phrase, when matched and confirmed, activates the recently-woken state. Wake-word *groups* (with `id`, per-group `aliases`, per-group `triggers`, `lang`, `skip_unmatched_inline`) SHALL NOT exist.

#### Scenario: Flat list parsed

- **WHEN** `wake_words` is `["ehi assistente", "ascolta assistente", "aiuto"]`
- **THEN** each string is a wake phrase
- **AND** matching any one of them opens the recently-woken window

#### Scenario: Legacy group mapping rejected with guidance

- **WHEN** `wake_words` contains a group mapping (e.g. `- word: ... id: ...`)
- **THEN** the loader raises a `ConfigError` (or warns) directing the user to the flat-list form
