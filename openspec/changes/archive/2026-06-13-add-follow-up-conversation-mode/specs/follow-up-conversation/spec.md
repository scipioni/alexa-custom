## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Command recognition window
After wake word detection, the system SHALL open a full-transcription recognition window using the **stage-2 backend** (`stt.stage2`). The window duration is `recognition.command_timeout`. All other behaviour (trigger matching, timeout beep, MQTT publish) is unchanged.

After a command is matched and dispatched, if follow-up mode is active for the dispatched trigger (see "Follow-up conversation window"), the system SHALL re-open a command window without requiring the wake word, using `recognition.follow_up_timeout`; otherwise it SHALL resume stage-1 wake-word listening as before.

#### Scenario: Command captured using stage-2 backend
- **WHEN** wake word is detected with stage1=vosk and stage2=sherpa-onnx
- **THEN** the command window uses the sherpa-onnx model for transcription

#### Scenario: Command matched using group triggers
- **WHEN** wake word group "galileo" has its own triggers and the user speaks a matching phrase
- **THEN** the corresponding actions are dispatched

#### Scenario: Command matched using global fallback triggers
- **WHEN** wake word group "assistente" has no triggers defined and the user speaks a phrase matching a global trigger
- **THEN** the corresponding actions are dispatched using the global fallback trigger list

#### Scenario: Command window timeout
- **WHEN** no speech or no matching phrase is detected within `recognition.command_timeout` seconds
- **THEN** the system plays a timeout beep and resumes wake word listening with stage-1

#### Scenario: Custom timeout configured
- **WHEN** `recognition.command_timeout: 5.0` is set
- **THEN** the command window stays open for 5 seconds

#### Scenario: No triggers anywhere
- **WHEN** a wake word group has no triggers and the global triggers list is also empty
- **THEN** the command window opens, nothing matches, the timeout beep plays, and the system returns to Stage 1

#### Scenario: Follow-up window opens after a match when enabled
- **WHEN** `recognition.follow_up: true` and a command is matched and dispatched
- **THEN** after the action's audio finishes the system opens a follow-up window (using `recognition.follow_up_timeout`) instead of returning directly to wake-word listening

### Requirement: recognition: block schema
The `recognition:` block SHALL accept:

| Field | Default | Description |
|---|---|---|
| `mode` | `"two-stage"` | `"two-stage"` or `"single-stage"` |
| `command_timeout` | `3.0` | Seconds to listen for command after wake |
| `wake_tone` | `"wake"` | Tone name played on wake detection |
| `follow_up` | `false` | Master switch: re-open a command window after a match without requiring the wake word |
| `follow_up_timeout` | `4.0` | Silence window (seconds) for each follow-up turn |
| `follow_up_max_turns` | `5` | Maximum consecutive follow-up turns before the window closes |
| `follow_up_tone` | `"info"` | Tone name played when a follow-up window opens |

The `confidence` field is removed from this block; it moves to `stt.stage1.confidence`.

#### Scenario: recognition block parsed
- **WHEN** `recognition: {mode: two-stage, command_timeout: 5.0}`
- **THEN** `config.recognition.command_timeout` equals `5.0`

#### Scenario: follow-up fields parsed
- **WHEN** `recognition: {follow_up: true, follow_up_timeout: 3.0, follow_up_max_turns: 4}`
- **THEN** `config.recognition.follow_up` is `True`, `follow_up_timeout` is `3.0`, and `follow_up_max_turns` is `4`

#### Scenario: follow-up defaults when absent
- **WHEN** the `recognition:` block omits the follow-up fields
- **THEN** `config.recognition.follow_up` is `False`, `follow_up_timeout` is `4.0`, `follow_up_max_turns` is `5`, and `follow_up_tone` is `"info"`
