# Capability: STT Capture Recovery

## Purpose
Detect and recover from stalled or failed audio capture and STT model loading so the recognition pipeline self-heals without a daemon restart, and so config/device changes take effect on a running capture without staleness.

## Requirements

### Requirement: Stalled-capture detection and restart
The gated-audio iterator SHALL track the time since the last byte was received from the capture subprocess. When the subprocess is still alive but has delivered no data for longer than `stt.capture_stall_secs` (default 30 s), the system SHALL log an ERROR identifying the stall and return from the iterator so the existing worker restart path terminates the capture subprocess, re-resolves the capture source, and restarts capture. Silence delivered as zero-filled frames SHALL NOT count as a stall (bytes are still flowing).

#### Scenario: Capture process alive but wedged
- **WHEN** the capture subprocess stops delivering bytes for longer than `capture_stall_secs` without exiting (e.g. a wedged PulseAudio stream after a USB reset)
- **THEN** an ERROR is logged and capture is torn down and restarted in-process, restoring listening without a daemon restart

#### Scenario: Quiet room with hardware noise gating
- **WHEN** the microphone hardware gates silence to digital-zero frames for minutes
- **THEN** no stall is detected because zero-filled frames still count as received data

### Requirement: STT model load retried on any failure
The STT worker SHALL catch all exceptions (not only `RuntimeError`) raised while loading the STT backend/model, log them at ERROR level, and retry the load with backoff (initial 10 s, doubling to a 60 s cap) instead of terminating the worker thread.

#### Scenario: Corrupt model directory
- **WHEN** the model loader raises an unexpected exception (e.g. corrupt or partially downloaded model files)
- **THEN** the worker thread stays alive, logs the error on each attempt, and recovers automatically once the model directory is repaired

### Requirement: Recognition loop reacts to config and device changes
The recognition loop SHALL observe a change-generation signal bumped by config hot-reload and by audio-device reconnection. Within one chunk iteration (≤ 2 s) of the signal changing, the loop SHALL exit to the outer worker loop, which re-reads configuration and re-resolves the capture source. A healthy long-running capture SHALL NOT prevent config changes or a replugged device's new node name from taking effect.

#### Scenario: Wake word edited while capture is healthy
- **WHEN** `conf/config.yaml` gains a new wake phrase and the config reload succeeds while capture has been running for days
- **THEN** the recognition loop restarts within one chunk iteration and the new phrase is active without a daemon restart

#### Scenario: Device replugged with a new node name
- **WHEN** the USB audio device is replugged and the audio watcher signals reconnection
- **THEN** the capture source is re-resolved to the new node and capture resumes on it
