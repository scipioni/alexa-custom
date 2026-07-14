# Capability: Follow-up Conversation

## Purpose
Allow the system to re-open a command-listening window after a command is dispatched, without requiring the wake word again, enabling multi-turn interactions within a single session.

## Requirements

### Requirement: Follow-up conversation window

After a command is matched and its actions are dispatched, the system MAY re-open a command-listening window **without requiring the wake word**, when follow-up mode is active for the dispatched trigger. The window reuses the stage-2 capture path (`capture_transcript`) and stays sequential — it SHALL open only after the dispatched action's audio has finished and the capture pipe has been drained of echo — so the system never listens over its own speech.

The follow-up window SHALL be governed by:
- a global master switch `recognition.follow_up` (default `false`);
- an optional per-trigger override `follow_up` on the matched trigger: `true` or `false` overrides the global default for that trigger; absent (unset) inherits the global default.

When the follow-up window is active, the system SHALL:
1. drain the capture pipe to remove TTS echo, then play the `recognition.follow_up_tone` cue;
2. capture one turn using `recognition.follow_up_timeout` as the silence window;
3. on a captured turn, match it against triggers and dispatch as a normal command (no wake word), then repeat;
4. close the window and return to wake-word listening on any termination condition below.

The window SHALL close when any of these occur:
- the capture returns no speech within `follow_up_timeout` (silence);
- the captured turn is an exit phrase (per the configured exit-phrase detection);
- the captured turn matches no trigger and no LLM fallback is configured;
- `recognition.follow_up_max_turns` consecutive follow-up turns have been taken;
- a LiveKit call is active.

#### Scenario: Follow-up continues without wake word

- **WHEN** `recognition.follow_up: true` and the user says (after the wake word) `"accendi le luci"`, then after the chime says `"spegni le luci"`
- **THEN** the first command dispatches, the follow-up chime plays, and the second command dispatches without the user repeating the wake word

#### Scenario: Silence closes the window

- **WHEN** a follow-up window is open and no speech is captured within `follow_up_timeout`
- **THEN** the window closes and the system returns to wake-word listening

#### Scenario: Exit phrase closes the window

- **WHEN** a follow-up window is open and the user says an exit phrase (e.g. `"basta"`, `"grazie"`)
- **THEN** the window closes without dispatching a command

#### Scenario: Max-turns cap closes the window

- **WHEN** `recognition.follow_up_max_turns: 3` and three consecutive follow-up turns have been captured
- **THEN** no further follow-up window opens and the system returns to wake-word listening

#### Scenario: Per-trigger opt-out overrides global enable

- **WHEN** `recognition.follow_up: true` and the matched trigger sets `follow_up: false`
- **THEN** no follow-up window opens after that command

#### Scenario: Per-trigger opt-in overrides global disable

- **WHEN** `recognition.follow_up: false` and the matched trigger sets `follow_up: true`
- **THEN** a follow-up window opens after that command

#### Scenario: Disabled by default

- **WHEN** `recognition.follow_up` is unset and no trigger sets `follow_up`
- **THEN** the system behaves exactly as today — one command per wake word, no follow-up window

#### Scenario: Suppressed during an active call

- **WHEN** a LiveKit call is active after a command dispatches
- **THEN** no follow-up window opens (STT is gated during the call)

#### Scenario: No-match falls through to LLM when configured

- **WHEN** a follow-up turn matches no trigger and `llm.fallback_on_no_match` is enabled
- **THEN** the turn is handled by the `llm_chat` action, after which the system returns to wake-word listening

#### Scenario: Action confirmation does not echo into the follow-up turn

- **WHEN** a dispatched action speaks a TTS confirmation and a follow-up window then opens
- **THEN** the capture pipe is drained first so the follow-up turn does not capture the system's own speech
