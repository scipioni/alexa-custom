# Capability: Audio Management

## Purpose
Proactively manage PipeWire hardware profiles and routing to ensure reliable audio operation in a headless environment.

## Requirements

### Requirement: Proactive PipeWire state enforcement
The system SHALL run a background daemon thread that monitors PipeWire events and ensures that the configured audio hardware is correctly initialized and routed. The target audio card name SHALL be sourced from `config.audio_card_name` (default `"NewPie"`) rather than being hardcoded. A `configure(cfg)` function SHALL be provided to update the module-level audio parameters after each config load or hot-reload.

#### Scenario: Device profile enforced on connect
- **WHEN** a configured Bluetooth device connects in A2DP mode
- **THEN** the system automatically switches it to the `headset-head-unit` (mSBC) profile to enable the microphone

#### Scenario: Default routing snatched back
- **WHEN** another audio device (e.g., HDMI) becomes the default PipeWire sink while the configured device is connected
- **THEN** the system automatically snatches back the default status for the configured device

#### Scenario: Custom audio_card_name used for device search
- **WHEN** `config.yaml` sets `audio_card_name: ConferenceCam` and `audio.configure(cfg)` is called
- **THEN** `find_alexa_card()` matches cards containing `conferencecam` (case-insensitive) instead of `newpie`

### Requirement: Adaptive session sample rates
The system SHALL detect the connection type of the active audio device and adjust the LiveKit session parameters accordingly. Sample rates SHALL be sourced from `config.audio_sample_rates` (with defaults `usb: 48000`, `bluetooth: 16000`, `internal: 48000`) rather than hardcoded constants.

#### Scenario: Bluetooth sample rate optimization
- **WHEN** the active audio device is detected as Bluetooth
- **THEN** the LiveKit session sample rate is set to the configured `audio_sample_rates.bluetooth` value (default 16000 Hz)

#### Scenario: Custom USB sample rate
- **WHEN** `config.yaml` sets `audio_sample_rates: {usb: 44100}`
- **THEN** the LiveKit session sample rate for a USB device is 44100 Hz

### Requirement: Audio status visualization
The system SHALL provide real-time visual feedback in the Terminal UI regarding the connection state and hardware configuration of the audio system.

#### Scenario: Device missing feedback
- **WHEN** the configured audio device is not detected
- **THEN** the TUI displays a yellow "Searching..." status and VU meters show a red "OFFLINE" label

#### Scenario: Device detected feedback
- **WHEN** the configured audio device is successfully initialized
- **THEN** the TUI status turns green and plays a two-tone ascending connection chime

### Requirement: Volume state persistence across restarts
The system SHALL persist the output volume level to `conf/state.yaml` after every change and SHALL restore it during daemon startup. Volume SHALL be stored as a `output_volume` key with a float value in the 0.0–1.0 range.

#### Scenario: Volume saved after voice command
- **WHEN** the volume is changed to 0.80 via voice command
- **THEN** `conf/state.yaml` is updated with `output_volume: 0.8`

#### Scenario: Volume restored on daemon start
- **WHEN** the daemon starts and `conf/state.yaml` contains `output_volume: 0.8`
- **THEN** the system applies 0.8 as the initial output volume

### Requirement: Optimized peak calculation
The system SHALL calculate audio peak levels directly from raw `int16` sample buffers without casting the entire buffer to floating point numbers, in order to minimize CPU utilization and memory allocation overhead.

#### Scenario: Peak calculation performance
- **WHEN** an audio frame is processed for volume metrics
- **THEN** the peak is derived directly from the integer amplitude before normalization.

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
