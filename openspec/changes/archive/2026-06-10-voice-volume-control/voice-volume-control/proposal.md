## Why

Currently, volume adjustments require manual interaction or fixed preset triggers. The user wants natural voice control: saying "volume al 80%" should immediately set the system volume to 80% without predefined presets. This makes the assistant feel more responsive and practical for daily use.

## What Changes

- New action type `set_volume_from_transcript` that receives the raw STT transcript, parses a percentage value from it, and sets the system volume
- A trigger definition in `system.yaml` matching "volume al" (and aliases) that routes to the new action type
- Italian number word parser to handle spoken percentages ("ottanta per cento", "80%", "volume al 50")
- Volume state persisted to `conf/state.yaml` and restored on daemon startup

## Capabilities

### New Capabilities
- `voice-volume-control`: Parse percentage values from Italian voice commands and set the system output volume

### Modified Capabilities
- `action-dispatch`: Add `set_volume_from_transcript` to the set of recognized action types
- `audio-management`: Volume state persistence and startup restoration (may need delta spec if requirements change)

## Impact

- `alexa_custom/actions.py` — new action handler `handle_set_volume_from_transcript`
- `alexa_custom/audio_hw.py` — volume persistence already exists, may need minimal wiring
- `alexa_custom/client.py` — ensure startup volume restoration
- `conf/actions/system.yaml` — new trigger entry for "volume al"
- New file: `alexa_custom/number_parser.py` — Italian number word → float conversion
