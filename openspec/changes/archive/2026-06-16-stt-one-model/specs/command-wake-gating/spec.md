## ADDED Requirements

### Requirement: Per-trigger with_wake flag

Each trigger SHALL declare a boolean `with_wake`. When `with_wake` is `false`, the trigger's commands fire whenever matched, regardless of wake state. When `with_wake` is `true`, the trigger's commands fire only if a wake word was recently detected.

#### Scenario: Direct command (with_wake false)

- **WHEN** a trigger has `with_wake: false`
- **AND** one of its `commands` matches a confirmed transcript
- **THEN** the trigger's actions are dispatched without requiring any prior wake word

#### Scenario: Wake-gated command (with_wake true), not woken

- **WHEN** a trigger has `with_wake: true`
- **AND** one of its `commands` matches but no wake word is currently active
- **THEN** the trigger does not fire

#### Scenario: Wake-gated command (with_wake true), woken

- **WHEN** a wake word was detected within the wake window
- **AND** a `with_wake: true` trigger's command matches a confirmed transcript
- **THEN** the trigger's actions are dispatched

#### Scenario: Default when omitted

- **WHEN** a trigger omits `with_wake`
- **THEN** it defaults to `with_wake: true` (a wake word is required)

### Requirement: Recently-woken state with timeout

Detecting a configured wake word SHALL set a "recently woken" state that remains active for a configurable window. The window SHALL expire after the timeout, returning the system to the un-woken state.

#### Scenario: Wake word activates the window

- **WHEN** a configured wake word is matched and confirmed by silence
- **THEN** the good tone is emitted
- **AND** the recently-woken window opens for `wake_window` seconds

#### Scenario: Window expires

- **WHEN** `wake_window` seconds pass with no `with_wake: true` command matched
- **THEN** the recently-woken state clears
- **AND** subsequent `with_wake: true` commands no longer fire until a new wake word

#### Scenario: One-breath wake + command

- **WHEN** a single utterance contains a wake word immediately followed by a `with_wake: true` command
- **THEN** the wake word opens the window and the command matches within it
- **AND** the trigger fires from the single utterance

### Requirement: Commands list per trigger

Each trigger SHALL accept a list of `commands` (phrases). Matching any one of the listed commands against a confirmed transcript SHALL satisfy the trigger's phrase condition, subject to the configured fuzzy matching algorithm and threshold.

#### Scenario: Any command in the list matches

- **WHEN** a trigger lists multiple `commands`
- **AND** the transcript fuzzy-matches any one of them above `matching_threshold`
- **THEN** the trigger's phrase condition is satisfied

#### Scenario: Legacy phrase/aliases folded into commands

- **WHEN** a trigger uses the legacy `phrase` and/or `aliases` fields
- **THEN** the loader folds them into `commands` (`[phrase, *aliases]`)
- **AND** emits a deprecation warning

### Requirement: Patterns retained alongside commands

Triggers SHALL continue to support an optional `patterns` field of word-glob expressions, tested against the confirmed transcript before fuzzy command matching. Pattern matching behavior SHALL be unchanged from the prior implementation.

#### Scenario: Pattern matches before fuzzy

- **WHEN** a trigger defines `patterns` (e.g. `che tempo * domani`)
- **AND** the confirmed transcript matches a pattern
- **THEN** the trigger's phrase condition is satisfied without fuzzy command matching
- **AND** wake gating (`with_wake`) still applies to the trigger

### Requirement: Reply triggers use the commands shape

`on_reply` triggers (used by the `ask` action's reply window) SHALL use the same `commands` shape as top-level triggers. `with_wake` SHALL be ignored within a reply window. Reply matching SHALL continue to use `reply_matching_algorithm` and `reply_matching_threshold`.

#### Scenario: Reply matched via commands

- **WHEN** an `ask` action opens a reply window with `on_reply` triggers using `commands`
- **AND** the spoken reply matches one trigger's `commands` above `reply_matching_threshold`
- **THEN** that reply trigger's actions are dispatched

#### Scenario: with_wake ignored in reply window

- **WHEN** an `on_reply` trigger carries `with_wake`
- **THEN** the flag has no effect; the reply is matched regardless of wake state
