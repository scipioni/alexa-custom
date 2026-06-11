## 1. YAML Config Changes

- [x] 1.1 Remove "alza il volume" and "abbassa il volume" entries from `conf.example/actions/user.yaml`
- [x] 1.2 In `conf.example/actions/system.yaml`: remove "volume al" trigger entry, add three new preset triggers (Volume basso → 0.1, Volume medio → 0.5, Volume alto → 0.9) using `set_volume` with `mode: absolute`

## 2. Remove Dead Code

- [x] 2.1 Remove `handle_set_volume_from_transcript()` function and its `@registry.register` decorator from `alexa_custom/actions.py`
- [x] 2.2 Delete `alexa_custom/number_parser.py` module
- [x] 2.3 Remove `set_volume_from_transcript` test cases from `tests/test_actions.py`
- [x] 2.4 Delete `tests/test_number_parser.py`

## 3. Fix Page Reload Bug

- [x] 3.1 Remove `await self._broadcast({"type": "reload"})` from `_asset_watcher_loop` in `alexa_custom/web.py`
- [x] 3.2 Remove `case 'reload': location.reload(); break;` from the WebSocket message handler in `alexa_custom/dashboard.html`

## 4. Cleanup

- [x] 4.1 Delete archived change directory `openspec/changes/archive/2026-06-10-voice-volume-control/`
- [x] 4.2 Verify lint + tests pass
