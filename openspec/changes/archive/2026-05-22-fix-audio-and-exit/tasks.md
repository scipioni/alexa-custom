# Tasks: Fix Audio and Exit

- [x] **Research and Validation**
    - [x] Confirm `pw-play` command line syntax for reading from stdin.
    - [x] Verify `os._exit(0)` location in `client.py`.

- [x] **Implementation - Robust Audio**
    - [x] Create `_play_raw` helper in `audio.py`.
    - [x] Refactor `play_beep` to use `_play_raw`.
    - [x] Refactor `play_startup_chime` to use `_play_raw`.
    - [x] Ensure `stderr=subprocess.DEVNULL` is used in all audio `run`/`Popen` calls.

- [x] **Implementation - Silent Shutdown**
    - [x] Update `start_parec` in `stt.py` to use `stderr=subprocess.DEVNULL`.
    - [x] Add `time.sleep(0.2)` before `os._exit(0)` in `client.py`.

- [x] **Verification**
    - [x] Run `alexa-client --tui` and verify startup chime is audible.
    - [x] Press 'q' and verify no "Broken pipe" message appears.
    - [x] Verify that STT still works correctly before quitting.
