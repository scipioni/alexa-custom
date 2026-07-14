## Why

The current volume control via voice is incremental ("alza/abbassa il volume" ±10%) combined with a fragile transcript-parsing approach ("volume al X%"). This duplicates functionality while adding dead code, an unused module (`number_parser`), and a bug where saving the volume to config.yaml triggers a full page reload in the web dashboard. Replacing all three with simple preset commands eliminates the complexity and the bug in one pass.

## What Changes

- **Delete** 3 voice triggers: `alza il volume`, `abbassa il volume` (from `conf.example/actions/user.yaml`), `volume al` (from `conf.example/actions/system.yaml`)
- **Add** 3 new preset triggers in `system.yaml`: `Volume basso` → 10%, `Volume medio` → 50%, `Volume alto` → 90%
- **Remove** dead code: `handle_set_volume_from_transcript()` action handler, `number_parser.py` module, and all associated tests
- **Remove** the archived change `2026-06-10-voice-volume-control`
- **Fix** the page-reload bug: remove `{"type": "reload"}` broadcast from `_asset_watcher_loop` (web.py) and the corresponding JS `location.reload()` handler (dashboard.html)
- **BREAKING**: Remove `set_volume_from_transcript` action type from the dispatch registry

## Capabilities

### New Capabilities
- `volume-presets`: Three voice-activated preset volume levels (basso=10%, medio=50%, alto=90%) using the existing `set_volume` action type with absolute values.

### Modified Capabilities
- `action-dispatch`: Remove the `set_volume_from_transcript` action type requirement and its scenarios from the spec.
- `web-interface`: Fix the asset-watcher broadcast that causes full page reload on config changes.

## Impact

- `alexa_custom/actions.py` — remove `handle_set_volume_from_transcript()` (lines 425-449)
- `alexa_custom/number_parser.py` — delete entire module
- `alexa_custom/web.py` — remove `{"type": "reload"}` broadcast from `_asset_watcher_loop` (line 392)
- `alexa_custom/dashboard.html` — remove `case 'reload'` from WS handler (line 1537)
- `conf.example/actions/user.yaml` — remove 2 trigger entries (alza/abbassa)
- `conf.example/actions/system.yaml` — remove "volume al" trigger entry, add 3 new preset trigger entries (basso/medio/alto)
- `tests/test_actions.py` — remove ~10 test cases for `set_volume_from_transcript`
- `tests/test_number_parser.py` — delete entire test file
- `openspec/changes/archive/2026-06-10-voice-volume-control/` — delete entire archived change directory
