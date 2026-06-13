## Context

The wake→command→action flow runs in `_wake_detected()` (`alexa_custom/stt.py`, ~line 1095), called from both the single-stage and two-stage STT loops. It is a self-contained straight line: play wake beep → `capture_transcript()` → `match_trigger()` → `dispatch()` → `return`. After it returns, the STT loop resets stage-1 state and goes back to idle, requiring the wake word again.

Stage-2 capture machinery already handles everything a follow-up turn needs:
- `capture_transcript(proc, channels, backend, timeout, …)` — gated capture of one command utterance with VAD endpointing.
- `_drain_pipe(proc)` — wipes acoustic echo / stale frames buffered while playback held STT gated.
- `match_trigger(transcript, triggers, algorithm, threshold)` — selects a trigger.
- `dispatch(trigger, …, listen_fn, on_stt_event, …)` — runs the trigger's actions on the dispatch loop.
- `is_exit_phrase(text, exit_phrases)` (in `alexa_custom/llm.py`) — detects "basta"/"grazie"/"stop".

This change re-flows those into a loop after a successful dispatch. Stage 1 (wake detection) and `capture_transcript` internals are untouched.

## Goals / Non-Goals

**Goals:**
- After a matched command, optionally re-open a command window without the wake word.
- Reuse the proven stage-2 capture path; add no new audio capture code.
- Stay sequential (window opens only after the action's audio finishes) so echo is never an issue.
- Zero behavior change when follow-up is disabled (the default).
- Per-trigger control so a command can opt out (or opt in) of follow-up.

**Non-Goals:**
- No barge-in / mid-TTS interruption (needs AEC — separate effort).
- No changes to wake detection, streaming-intent detection, or `capture_transcript`.
- No follow-up wrapping inside `llm_chat` (it owns its own multi-turn loop and exit phrases).

## Decisions

### Extract `_handle_command`, wrap in a loop
The capture→match→dispatch tail of `_wake_detected` (lines ~1139–1239, including the `fallback_on_no_match` → `llm_chat` branch and the matched-dispatch branch) moves into `_handle_command(transcript: str) -> bool`, returning `True` iff a trigger matched (or LLM fallback fired). `_wake_detected` then becomes: capture the first transcript → `matched = _handle_command(transcript)` → follow-up loop while `matched`. Keeping a single function avoids threading new state through the STT loop call sites.

### Loop shape and termination
```
matched = _handle_command(first_transcript)
turns = 0
while follow_up_active(wake_group, trigger, config) and matched \
        and not livekit_connected_flag.is_set() \
        and turns < config.recognition.follow_up_max_turns:
    turns += 1
    _drain_pipe(proc)                      # wipe TTS echo from the just-run action
    play_wake_beep(config.recognition.follow_up_tone)
    set state "listening" (MQTT + on_stt_event)
    transcript = capture_transcript(..., config.recognition.follow_up_timeout, ...)
    if not transcript: break               # silence closes the window
    if is_exit_phrase(transcript, exit_phrases): break
    matched = _handle_command(transcript)  # no-match → matched False → loop ends
```
A turn that does not match a trigger sets `matched = False`, which ends the loop after the (optional) LLM fallback inside `_handle_command` — i.e. an off-script utterance either becomes an `llm_chat` turn (if `fallback_on_no_match`) or closes the window with the timeout tone. This reuses the existing no-match behavior verbatim.

### Per-trigger override resolves against the matched trigger
`follow_up_active()` returns: the matched `trigger.follow_up` if it is not `None`, otherwise `config.recognition.follow_up`. The override is read from the trigger that was *just dispatched*, so the decision to keep listening is governed by the command the user actually ran (e.g. "buonanotte" with `follow_up: false` ends the conversation even when the global flag is on). When no trigger matched (LLM fallback path), fall back to the global flag.

### Echo safety: drain before every follow-up capture
Dispatched actions may speak (`say`, `set_volume` confirmation, `llm_chat`). Opening the mic immediately would capture the tail of the system's own TTS. `_drain_pipe(proc)` immediately before each `capture_transcript`, combined with the existing `post_playback_ms` gating in `_iter_gated_audio`, guarantees the follow-up turn starts from fresh audio. This is the same pattern already used after `_wake_detected` dispatch in the STT loops.

### Suppress during LiveKit call
If `livekit_connected_flag.is_set()`, the loop never starts (and breaks if a call begins mid-conversation). During a call STT is gated, so a follow-up window would be dead time and could fight the gating state.

### Config surface and defaults
`RecognitionConfig` gains:
- `follow_up: bool = False` — master switch (opt-in).
- `follow_up_timeout: float = 4.0` — silence window per follow-up turn (shorter than `command_timeout` so the conversation closes promptly).
- `follow_up_max_turns: int = 5` — runaway guard against background speech.
- `follow_up_tone: str = "info"` — subtle "still listening" chime distinct from the wake beep.

`Trigger` gains `follow_up: bool | None = None` (tri-state: inherit / force-on / force-off). Parsing mirrors existing optional-field handling; absent → `None` → inherits global.

## Risks / Trade-offs

- **Window lingers on background speech / TV** → noise could be transcribed as a (non-matching) turn each cycle. Mitigation: `follow_up_max_turns` cap; short `follow_up_timeout`; a non-matching turn with no LLM fallback closes the window immediately.
- **Capturing TTS echo of the action's own confirmation** → mitigated by `_drain_pipe` + `post_playback_ms`; covered by an explicit test (TTS-confirming action must not echo into the follow-up capture).
- **Surprise for users who expect wake-per-command** → feature is off by default; documented; per-trigger `follow_up: false` lets specific commands opt out even when globally on.
- **Interaction with `llm_chat`** → `llm_chat` already runs its own multi-turn loop; a follow-up window wrapping an `llm_chat` dispatch would double-loop. Decision: when the matched trigger's action is `llm_chat`, the follow-up loop does not add a turn on top (the `llm_chat` loop already consumed the conversation, and on its exit we return to idle). Treated as `follow_up: false` implicitly for `llm_chat`-only triggers.
- **Refactor risk in a hot path** → `_handle_command` extraction must preserve the exact MQTT command publish, metrics (`commands_matched`), and `on_stt_event` calls. Covered by keeping existing tests green plus the new behavioral tests.
