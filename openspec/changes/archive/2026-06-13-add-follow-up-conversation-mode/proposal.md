## Why

Every command today requires the wake word. Asking for two related things in a row means two wakes: *"galileo, accendi le luci"* … *"galileo, spegni le luci"*. Multi-turn interaction only exists inside the `llm_chat` action, which manages its own listen loop. For ordinary triggers, the assistant always falls back to idle and waits for the wake word again after each command.

A short **follow-up window** after a successful command lets the user keep talking without re-waking. Because the window opens *after* the dispatched action's audio has finished, it is always sequential — the system never listens over its own TTS — so it sidesteps the acoustic-echo problem that the STT gating exists to work around (no AEC on this board). Every building block already exists in the tree (`capture_transcript`, `_drain_pipe`, `match_trigger`, `dispatch`, `is_exit_phrase`); the change is mostly re-flowing them into a loop.

## What Changes

- `_wake_detected()` (`alexa_custom/stt.py`) is refactored: the capture→match→dispatch tail (currently a straight line ending in `return`) is extracted into a helper `_handle_command(transcript) -> bool` returning whether a trigger matched, and wrapped in a follow-up loop.
- After a successful matched dispatch, when follow-up mode is enabled, the system:
  1. drains the capture pipe (`_drain_pipe`) to wipe any TTS echo, then plays a subtle "still listening" chime (`follow_up_tone`);
  2. captures another turn via the existing `capture_transcript` with a shorter `follow_up_timeout`;
  3. on silence, an exit phrase (`is_exit_phrase`), or reaching `follow_up_max_turns`, closes the window and returns to idle;
  4. otherwise matches + dispatches the turn (reusing `_handle_command`) and loops — **no wake word required**.
- Scope: **global flag with per-trigger override.** `RecognitionConfig` gains `follow_up: bool` (master switch, default off). A `Trigger` gains an optional `follow_up: bool | None` field; `True`/`False` overrides the global default for that trigger (e.g. a "buonanotte" command sets `follow_up: false`).
- No-match inside a follow-up turn reuses the existing path: if `config.llm.fallback_on_no_match` is set, the turn falls through to `llm_chat`; otherwise the window closes with the timeout tone.
- Suppress the follow-up window entirely while a LiveKit call is active (STT is gated anyway).
- Off by default → no behavior change for anyone who does not enable it. PATCH-safe.

Out of scope (decided during exploration): no barge-in / interrupting TTS mid-utterance (requires AEC — separate spike); no changes to stage-1 wake detection or `capture_transcript` internals; no follow-up nesting inside `llm_chat` (it already runs its own multi-turn loop); no new audio capture path.

## Capabilities

### New Capabilities
- `follow-up-conversation`: after a successful command, the system MAY re-open a command-listening window without requiring the wake word, governed by a global flag and per-trigger override, with silence/exit-phrase/max-turn termination and call-active suppression.

### Modified Capabilities
- `wake-word-detection`: the post-dispatch behavior of `_wake_detected` gains an optional follow-up loop; the default (follow-up disabled) path is unchanged.
- `yaml-config`: `RecognitionConfig` gains follow-up knobs and `Trigger` gains a `follow_up` override field.

## Impact

- **Code**: `alexa_custom/stt.py` (`_wake_detected` refactor + follow-up loop, new `_handle_command` helper); `alexa_custom/config.py` (`RecognitionConfig` fields, `Trigger.follow_up`, parsing); reuses `alexa_custom/llm.py` `is_exit_phrase`.
- **Config**: new optional `recognition.follow_up`, `follow_up_timeout`, `follow_up_max_turns`, `follow_up_tone` keys; optional `follow_up` key on trigger entries. No migration required.
- **Tests**: `tests/` — follow-up loop continues without wake word, silence closes window, exit phrase closes window, max-turns cap, per-trigger override, suppression during LiveKit call, TTS-confirming action does not echo into the follow-up capture.
- **Dependencies**: none added.
