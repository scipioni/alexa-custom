## Context

The system already has `handle_set_volume` in `actions.py:393` which supports absolute/up/down modes via fixed params, and `set_output_volume()` in `audio_hw.py:216` which executes `wpctl set-volume`. Volume state persistence already partially exists via `save_volume_state()` / `load_volume_state()` writing to `conf/state.yaml`.

What's missing is the glue layer: parsing a variable percentage value from a raw transcript and routing it to the existing volume machinery. The fuzzy trigger matcher can match "volume al" as a static phrase, but cannot extract the "80%" portion — that requires a new action type that receives the transcript and does its own parsing.

## Goals / Non-Goals

**Goals:**
- New `set_volume_from_transcript` action type registered in `actions.py`
- Italian number parser module that handles digits, percentages, and number words 0–100
- Trigger entry in `system.yaml` matching "volume al" and aliases
- Volume state saved after every voice adjustment and restored on startup
- Confirmation tone after successful volume change

**Non-Goals:**
- Relative volume adjustments ("più alto", "più basso") — future iteration
- Volume display or feedback via TTS announcing the level — just a tone for now
- Multi-language support — Italian only
- Values above 100 — clamped
- Integration with the web dashboard volume slider — already separately handled

## Decisions

### 1. New action type vs. variable capture in trigger engine
**Decision**: New `set_volume_from_transcript` action type (Option D from exploration).

**Rationale**: A generic `{value}` capture mechanism in the trigger engine would be more elegant but is a much larger change touching `config.py` models, `match_trigger()`, parameter expansion, and dispatch. A dedicated action type is ~50 lines of focused code, zero ripple to the matching engine, and can be generalized later when a second use case emerges (e.g., "timer di 5 minuti").

### 2. Transcript passed as `transcript` kwarg
**Decision**: The action handler receives the raw transcript via the existing `dispatch()` context (already passes `transcript=` to `_run_action`).

**Rationale**: No changes needed to `dispatch()` — it already passes the transcript through. The handler just needs to accept and use it.

### 3. Italian number parser as standalone module
**Decision**: New file `alexa_custom/number_parser.py` with a single function `parse_percentage(transcript: str) -> float | None`.

**Rationale**: Isolates the parsing logic for testability. The function is small enough to be pure (no state, no I/O). The spec only requires numbers 0–100, so we can write a compact lookup-based parser.

### 4. Confirmation via tone only (no TTS)
**Decision**: Play the existing "info" tone after volume change, skip TTS announcement.

**Rationale**: A TTS announcement ("Volume impostato all'80%") adds latency, requires the TTS pipeline to be available, and is annoying during repeated adjustments. A brief tone signals success without verbal overhead.

## Data Flow

```
STT transcript
    │
    ▼
match_trigger("volume al 80%")
    │ fuzzy match against "volume al" trigger
    ▼
dispatch(set_volume_from_transcript, transcript="volume al 80%")
    │
    ▼
handle_set_volume_from_transcript(transcript="volume al 80%", ...)
    │
    ├─▶ number_parser.parse_percentage("volume al 80%")
    │       │ regex for \d+%? | \d+ per cento | Italian number words
    │       ▼
    │   0.80  (or None if no number found)
    │
    ├─▶ if value is not None:
    │       set_output_volume(pulse, None, 0.80)
    │       save_volume_state(0.80)
    │       play_tone("info")
    │
    └─▶ if value is None: no-op (log debug)
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Italian number parser misses edge cases (e.g., "mille", "un centinaio") | Parser scoped to 0–100; unrecognized words return None (safe no-op) |
| PCM reset triggered by `pulsectl.Pulse()` connection inside the action handler | `set_output_volume()` already calls `_restore_hw_pcm()` after `wpctl` — no additional risk |
| STT transcribes "80" as "ottanta" but phonetic match on "volume al" still works | Fuzzy token matching handles extra/missing tokens; the trigger match is on "volume al" which doesn't contain the number |
| Conflicting with existing `set_volume` action type | Both coexist. `set_volume` is for fixed-param triggers (presets), `set_volume_from_transcript` is for variable voice commands. Different trigger phrases route to different types. |
| Volume set to 0% mutes audio silently | Intentional — user said "volume al 0%", that's what they get. Confirmation tone still plays. |
