# Delta: Audio Management

## ADDED Requirements

### Requirement: Output sink re-resolved after device replug
The system SHALL invalidate the cached output sink name when the audio watcher detects a device (re)connection, and SHALL re-resolve the sink lazily on the next playback. Playback SHALL never target a PipeWire node name that belonged to a device instance that has since been replugged or swapped.

#### Scenario: Device hot-swap
- **WHEN** the USB speakerphone is unplugged and a different (or the same) USB audio device is plugged in
- **THEN** the next playback resolves the current sink node and plays audibly, without a daemon restart or config edit

### Requirement: Playback failures are logged
Every playback path (file playback, array playback, raw playback) SHALL check the player subprocess result and log the return code and stderr at WARNING level or higher on failure. No playback path SHALL swallow exceptions or discard the player's stderr silently.

#### Scenario: pw-play fails against a stale target
- **WHEN** `pw-play` exits non-zero (e.g. its `--target` node no longer exists)
- **THEN** a WARNING with the return code and stderr appears in the journal instead of silent failure

### Requirement: Bounded subprocess calls in the audio enforcement path
All subprocess invocations in the audio enforcement and gain path (hardware mixer restore via `amixer`, source volume via `pactl`) SHALL specify a timeout (≤ 5 s). On timeout the call SHALL be abandoned with a WARNING log; the calling thread (including the audio watcher) SHALL continue operating. Capture-tool teardown SHALL escalate SIGTERM → SIGKILL after a bounded wait so a signal-ignoring subprocess cannot block a thread indefinitely.

#### Scenario: Hung amixer during USB replug
- **WHEN** an `amixer` call hangs on a wedged ALSA ioctl while the audio watcher enforces state
- **THEN** the call times out within 5 s, a WARNING is logged, and the watcher keeps running

#### Scenario: Capture tool ignores SIGTERM
- **WHEN** a capture subprocess does not exit after SIGTERM during teardown
- **THEN** it is killed with SIGKILL after a bounded wait and the teardown completes
