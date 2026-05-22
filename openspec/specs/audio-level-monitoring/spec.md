# Capability: Audio Level Monitoring

## Purpose
Monitor real-time audio levels for microphone and speaker tracks using direct stream tapping.

## Requirements

### Requirement: Direct Audio Stream Tapping
The system SHALL tap into the LiveKit `LocalAudioTrack` and subscribed `RemoteAudioTrack`s to capture raw audio frames for level calculation.

#### Scenario: Tap into Local Microphone Track
- **WHEN** the local microphone track is published
- **THEN** an `AudioStream` is attached to capture frames

#### Scenario: Tap into Remote Audio Tracks
- **WHEN** a remote audio track is subscribed
- **THEN** an `AudioStream` is attached to capture frames

### Requirement: Peak Level Calculation
The system SHALL calculate the peak level (0.0 to 1.0) of each audio frame using its raw PCM data.

#### Scenario: Calculate peak from 16-bit PCM
- **WHEN** an audio frame is received
- **THEN** the system calculates the maximum absolute value of the samples and normalizes it to a 0.0-1.0 range

### Requirement: Level Update Throttling
The system SHALL throttle the transmission of volume updates to the TUI to a maximum frequency of 10Hz (once every 100ms).

#### Scenario: Throttle volume events
- **WHEN** audio frames are processed continuously
- **THEN** the system emits a `volume_update` event no more frequently than once every 100ms

### Requirement: TUI Volume Visualization
The TUI SHALL update its VU meters based on the `volume_update` events received from the LiveKit session.

#### Scenario: Update VU meters from event
- **WHEN** a volume_update event is received by the TUI
- **THEN** the Microphone and Speaker VU meters are updated with the provided levels

### Requirement: Independent parec audio capture path for STT
The audio subsystem SHALL support a second independent microphone capture path using a `parec` subprocess at 16 kHz alongside the existing livekit `AudioStream` tap used for VU meters. The two paths MUST NOT interfere with each other.

#### Scenario: Both paths active simultaneously
- **WHEN** a LiveKit session is active and wake word detection is running
- **THEN** VU meters update via `AudioStream` tap and Vosk receives audio via `parec` concurrently without errors

#### Scenario: parec path active without LiveKit
- **WHEN** no LiveKit session is active
- **THEN** `parec` continues capturing and Vosk continues listening for wake words

