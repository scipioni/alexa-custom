## Why

Voice-controlled volume is the most natural way to adjust audio on a hands-free smart assistant. Currently, changing volume requires editing config.yaml or using shell commands — neither is accessible mid-conversation. Adding "alza il volume" / "abbassa il volume" as voice triggers closes this gap with minimal code.

## What Changes

- New `set_volume` action type in the action registry that accepts `mode: up|down|absolute`, `step` (relative), and `value` (absolute)
- Two new trigger entries in `conf/actions/user.yaml`: "alza il volume" → up 10%, "abbassa il volume" → down 10%
- Confirmation tone played on actual volume change
- A state persistence mechanism (`conf/state.yaml`) that saves the last user-set volume and restores it on daemon restart
- Load of state file in the audio configuration path, overriding `audio.output_volume` from config.yaml

## Capabilities

### New Capabilities
- `voice-volume-control`: Voice-triggered relative volume adjustment with state persistence

### Modified Capabilities
- (none — existing specs unchanged)

## Impact

- **`alexa_custom/actions.py`**: New `set_volume` handler registered via `@registry.register("set_volume")`
- **`alexa_custom/audio_hw.py`**: New `load_volume_state()` and `save_volume_state()` functions; `configure()` optionally loads state after config parse
- **`conf/actions/user.yaml`**: Two new trigger entries
- **`conf/state.yaml`**: New file (auto-created at first voice volume change, read at startup)
