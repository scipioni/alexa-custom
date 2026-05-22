# Proposal: Fix Startup Sound and Shutdown "Broken Pipe"

## Problem
1. **Startup Silence**: The `play_startup_chime` uses `aplay -D pipewire`, which is silent on many PipeWire configurations where the ALSA plugin is not mapped or pointing to the wrong default sink (e.g., HDMI).
2. **Shutdown Noise**: When quitting the TUI with `os._exit(0)`, the `parec` process in the STT thread is orphaned and eventually triggers a `write() failed: Broken pipe` error on its `stderr`, which leaks into the restored terminal.

## Proposed Solution

### 1. Robust Audio Playback
- Introduce a helper function `_play_raw` that prefers native PipeWire playback via `pw-play` if available.
- `pw-play` handles sample format conversion and routing more reliably than `aplay -D pipewire`.
- Fall back to `aplay` if `pw-play` is missing.

### 2. Silent Shutdown
- Redirect `stderr` of audio-related subprocesses (`parec`, `aplay`, `pw-play`) to `/dev/null`.
- This ensures that if a process is orphaned during `os._exit(0)`, its error messages don't clutter the user's terminal.
- Improve the shutdown sequence in `client.py` to trigger a clean termination of the STT thread before the hard exit.

## Scope
- `alexa_custom/audio.py`: Refactor `play_beep` and `play_startup_chime` to use the new robust playback helper.
- `alexa_custom/stt.py`: Silence `parec` `stderr`.
- `alexa_custom/client.py`: Update TUI shutdown logic to be more polite.

## Success Criteria
- Startup chime is audible on PipeWire systems.
- Quitting the TUI results in a clean return to the shell without "Broken pipe" messages.
