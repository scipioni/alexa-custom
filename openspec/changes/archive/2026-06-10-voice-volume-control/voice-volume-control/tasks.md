## 1. Number Parser Module

- [x] 1.1 Create `alexa_custom/number_parser.py` with `parse_percentage(transcript: str) -> float | None`
- [x] 1.2 Implement digit regex extraction: `\d+` optionally followed by `%` or `per cento`
- [x] 1.3 Implement Italian number word lookup for 0–100 (units, tens, compounds, "cento")
- [x] 1.4 Implement compound word splitting: `ventidue` → `venti` + `due` → 22
- [x] 1.5 Clamp result to 0.0–1.0 range
- [x] 1.6 Write unit tests in `tests/test_number_parser.py`

## 2. Action Handler

- [x] 2.1 Register `set_volume_from_transcript` action type via `@registry.register()`
- [x] 2.2 Implement `handle_set_volume_from_transcript()` that calls `parse_percentage()`
- [x] 2.3 Wire volume set: call `set_output_volume()` and `save_volume_state()` on success
- [x] 2.4 Play confirmation tone via `play_tone("info")` after volume change
- [x] 2.5 Handle no-match gracefully (no-op, log debug)
- [x] 2.6 Write unit tests for the action handler

## 3. Trigger Configuration

- [x] 3.1 Add trigger entry to `conf/actions/system.yaml`:
  - phrase: `"volume al"`
  - aliases: `["imposta volume a", "metti volume a", "volume"]`
  - type: `set_volume_from_transcript`

## 4. Startup Volume Restoration

- [x] 4.1 Verify `load_volume_state()` is called during daemon startup in `client.py`
- [x] 4.2 Verify initial volume is applied via `set_output_volume()` after loading state

## 5. Verification

- [x] 5.1 Run existing test suite: `task test`
- [x] 5.2 Run lint: `task lint`
- [x] 5.3 Run format check: `task format`
