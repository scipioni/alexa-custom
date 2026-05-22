# Design: Fix Audio and Exit

## 1. Robust Audio Playback

We will create a helper function in `audio.py` that abstracts the choice between `pw-play` and `aplay`.

### Helper Logic (`_play_raw`)
- Check for `pw-play` using `shutil.which`.
- If `pw-play` exists:
  - Command: `pw-play --rate=<rate> --channels=<ch> --format=f32 -- -`
  - (The `--` tells `pw-play` to read from stdin).
- Else (fallback to `aplay`):
  - Command: `aplay -D pipewire -r <rate> -f FLOAT_LE -c <ch> -q`
- **Crucial**: Always set `stderr=subprocess.DEVNULL`.

## 2. STT Silence

In `stt.py`, the `start_parec` function currently doesn't specify `stderr`.
- Update `subprocess.Popen` call to include `stderr=subprocess.DEVNULL`.
- This suppresses the "Broken pipe" message when the parent process exits abruptly.

## 3. Graceful-ish Shutdown

In `client.py`, the TUI exit path uses `os._exit(0)`.

```python
# Before
run_tui(...)
import os as _os
_os._exit(0)

# After
run_tui(...)
# Add a small grace period for threads to see the stop event
# that was set in AlexaTUI.on_unmount()
import time as _time
_time.sleep(0.2) 
import os as _os
_os._exit(0)
```

By adding a tiny 200ms delay after `run_tui` returns, we allow the STT thread's `finally` block (which terminates `parec`) to execute before the entire process tree is nuked.

## Visualizing the New Shutdown
```
[ TUI Quit ]
      │
      ▼
[ on_unmount ] ──▶ [ Set stt_stop Event ]
      │
      ▼
[ TUI loop ends ]
      │
      ▼
[ client.py ] ──▶ [ sleep(0.2) ] ──▶ [ STT Worker wakes up ]
      │                                    │
      │                                    ▼
      │                          [ proc.terminate() ]
      │                                    │
      ▼                                    ▼
[ os._exit(0) ] <────────────────── [ parec dies quietly ]
```
