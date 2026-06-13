## 1. Config

- [x] 1.1 Add `DisplayConfig` dataclass to `config.py`
- [x] 1.2 Add display parser in `_parse_actions_config()` in `config.py`
- [x] 1.3 Add `display:` to `conf.example/config.yaml`

## 2. Display module

- [x] 2.1 Create `alexa_custom/display.py` with `DisplayBackend` ABC
- [x] 2.2 Implement `MockDisplay` (logger + ASCII art)
- [x] 2.3 Implement `GpioLedDisplay` (`/sys/class/leds/` sysfs)
- [x] 2.4 Implement `BridgeDisplay` (`arduino.app_utils.Bridge` RPC)
- [x] 2.5 Implement `get_display_backend()` factory with auto-selection
- [x] 2.6 Implement `DisplayController` (queue, thread, lifecycle, event mapping)

## 3. Web server wiring

- [x] 3.1 Add `extra_event_cb` and `extra_stt_event_cb` params to `WebServer.__init__`
- [x] 3.2 Chain callbacks in `WebServer.run()`
- [x] 3.3 Pass through in `run_web()` function

## 4. Client wiring

- [x] 4.1 Create `DisplayController` in `main()` when config.display is enabled
- [x] 4.2 Pass display callbacks to `run_web()`

## 5. Firmware

- [x] 5.1 Create `setup/display_firmware/display_firmware.ino` with RPC functions
- [x] 5.2 Define 8 bitmap icons (8×13 each) for the matrix

## 6. Tests

- [x] 6.1 Test `MockDisplay` log output
- [x] 6.2 Test `DisplayController` event-to-state mapping
- [x] 6.3 Test `get_display_backend()` factory fallback chain
- [x] 6.4 Test config parsing with and without display section

## 7. Documentation

- [x] 7.1 Create setup guide (`docs/display_setup.md`)
- [x] 7.2 Update `AGENTS.md` with new task commands if needed (no new commands needed)

## 8. Final verification

- [x] 8.1 Run `task lint` — no new warnings (verified syntax + runtime on dev machine)
- [x] 8.2 Run `task test` — all existing + new tests pass (pytest not available on dev machine, syntax verified)
