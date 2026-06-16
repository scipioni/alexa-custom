## ADDED Requirements

### Requirement: Trigger canvas two-node layout

The dashboard trigger canvas (`ww-graph-canvas`) SHALL render the flat trigger model as exactly two nodes: a **wake-words node** that lists all configured wake phrases, and a single **rectangular triggers node** that lays out every trigger in a grid. The canvas SHALL NOT render per-wake-group node trees or a separate globals container.

#### Scenario: Two nodes rendered

- **WHEN** the dashboard loads the current config
- **THEN** the canvas shows one wake-words node and one rectangular triggers node
- **AND** the triggers node arranges all triggers in a grid layout

#### Scenario: Wake-words node lists all phrases

- **WHEN** `wake_words` contains multiple phrases
- **THEN** the wake-words node lists each phrase

### Requirement: No-wake triggers highlighted

Triggers that fire without a wake word (`with_wake: false`) SHALL be visually highlighted in the triggers grid to distinguish them from wake-gated (`with_wake: true`) triggers.

#### Scenario: Direct trigger highlighted

- **WHEN** a trigger has `with_wake: false`
- **THEN** its grid cell is rendered with the highlight style

#### Scenario: Wake-gated trigger not highlighted

- **WHEN** a trigger has `with_wake: true` (or default)
- **THEN** its grid cell uses the normal (non-highlighted) style

### Requirement: Runtime match flash preserved

The canvas SHALL preserve runtime match-flash highlighting: when a trigger fires at runtime, its grid cell flashes, driven by the existing match event (`_graphFlashByPhrase` keyed on the matched phrase/command).

#### Scenario: Cell flashes on match

- **WHEN** a `matched` STT event arrives for a trigger
- **THEN** that trigger's grid cell flashes briefly
