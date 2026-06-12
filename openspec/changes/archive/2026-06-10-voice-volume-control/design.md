## Context

The system already has an action registry (`ActionRegistry` in `actions.py`) with handlers for `log`, `telegram`, `livekit_join`, `say`, `ask`, `tone`, `shell`, `mqtt_publish`, `llm_chat`, and `llm_learn`. Volume is managed by `audio_hw.py` through `_OUTPUT_VOLUME` (a module-level float), `set_output_volume()` (wraps `wpctl set-volume` + `_restore_hw_pcm()`), and `get_output_volume()`. The volume is initialized from `config.yaml:audio.output_volume` at startup and is not currently persisted across restarts when changed at runtime.

The action dispatch pipeline is: STT transcript → `match_trigger()` (fuzzy Italian phonetic match) → `dispatch()` → `_run_action()` → `registry.execute()`.

## Goals / Non-Goals

**Goals:**
- New `set_volume` action handler registered in the existing registry
- Two trigger entries in `conf/actions/user.yaml` for "alza il volume" (up 10%) and "abbassa il volume" (down 10%)
- Confirmation tone on actual volume change
- Volume state persisted to `conf/state.yaml`, restored on restart

**Non-Goals:**
- No changes to the web dashboard volume slider or its persistence
- No MQTT publishing of volume state
- No Home Assistant entity for volume
- No volume normalization or EQ changes
- No input gain control via voice

## Decisions

### Decision: Inline tone vs chained action
The confirmation tone is played inside the `set_volume` handler rather than as a separate `tone` action in the trigger YAML. This allows the handler to only play the tone when an actual change occurs (skipping it when already at min/max). A separate YAML action would always fire regardless. Downside: the tone is not customizable per-trigger without code changes, which is acceptable for v1.

### Decision: State file over config.yaml writeback
`conf/state.yaml` is chosen over writing back to `config.yaml` because:
- `config.yaml` is user-edited and hot-reloaded; mutating it could trigger reload loops or confuse the user
- A dedicated state file is the standard pattern for separating user intent from runtime mutations
- Format: simple YAML (`output_volume: 0.6`), loaded after config parse in `configure()` or `load_volume_state()`

### Decision: Load state after configure()
The state file is loaded in a new `load_volume_state()` function called from `client.py` immediately after `configure()`. This ensures the module globals are set from config first, then overridden by the last-known runtime value. The override logs at debug level.

### Decision: Relative step via mode/step params
The `mode: up|down` approach with a `step` float is more flexible than hardcoding 10% in the handler. The YAML triggers set `step: 0.1` for the Italian phrases, but other triggers could use different step sizes or absolute mode without code changes.

### Decision: Use get_output_volume() as starting point
The handler reads the current volume from `get_output_volume()` (the in-memory global) rather than querying `wpctl get-volume`. This is faster, avoids a subprocess call, and is consistent with all other volume operations in the codebase. The global is kept in sync by `set_output_volume()` which is the only mutation path.

## Risks / Trade-offs

- **State file stale after external change**: If someone adjusts volume via `wpctl` or `pavucontrol` outside the app, `_OUTPUT_VOLUME` and `conf/state.yaml` become stale. On next voice adjustment, the handler reads the stale global as the starting point. **Risk**: a relative "up" from 0.5 might jump unexpectedly if the real hardware is at 0.3. **Mitigation**: acceptable for v1 — the primary use case is voice-only adjustment.
- **State file write failure**: If the filesystem is read-only or full, `save_volume_state()` fails silently (log warning, continue). **Risk**: volume not persisted across restart. **Mitigation**: log warning, no crash.
- **Race with hot-reload**: Config hot-reload calls `configure()` which resets `_OUTPUT_VOLUME` to `config.yaml`'s value. If a voice volume change and a config save happen simultaneously, the order is unpredictable. **Mitigation**: after the next voice change, the state file overrides again. If this becomes an issue, `configure()` could also load state.
