# Capability: Audio Management

## Purpose
Proactively manage PipeWire hardware profiles and routing to ensure reliable audio operation in a headless environment.

## Requirements

### Requirement: Proactive PipeWire state enforcement
The system SHALL run a background daemon thread that monitors PipeWire events and ensures that the configured audio hardware is correctly initialized and routed.

#### Scenario: Device profile enforced on connect
- **WHEN** a configured Bluetooth device connects in A2DP mode
- **THEN** the system automatically switches it to the `headset-head-unit` (mSBC) profile to enable the microphone

#### Scenario: Default routing snatched back
- **WHEN** another audio device (e.g., HDMI) becomes the default PipeWire sink while the configured device is connected
- **THEN** the system automatically snatches back the default status for the configured device

### Requirement: Adaptive session sample rates
The system SHALL detect the connection type of the active audio device and adjust the LiveKit session parameters accordingly to optimize CPU usage.

#### Scenario: Bluetooth sample rate optimization
- **WHEN** the active audio device is detected as Bluetooth
- **THEN** the LiveKit session sample rate is set to 16 kHz to improve stability on weak hardware

### Requirement: Audio status visualization
The system SHALL provide real-time visual feedback in the Terminal UI regarding the connection state and hardware configuration of the audio system.

#### Scenario: Device missing feedback
- **WHEN** the configured audio device is not detected
- **THEN** the TUI displays a yellow "Searching..." status and VU meters show a red "OFFLINE" label

#### Scenario: Device detected feedback
- **WHEN** the configured audio device is successfully initialized
- **THEN** the TUI status turns green and plays a two-tone ascending connection chime

### Requirement: Optimized peak calculation
The system SHALL calculate audio peak levels directly from raw `int16` sample buffers without casting the entire buffer to floating point numbers, in order to minimize CPU utilization and memory allocation overhead.

#### Scenario: Peak calculation performance
- **WHEN** an audio frame is processed for volume metrics
- **THEN** the peak is derived directly from the integer amplitude before normalization.
