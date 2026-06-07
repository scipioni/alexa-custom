## MODIFIED Requirements

### Requirement: Direct Audio Stream Tapping
The system SHALL tap into the LiveKit `LocalAudioTrack` for microphone level calculation. For remote tracks, level sampling SHALL be performed inside the existing playback pump loop rather than via a dedicated second `AudioStream` consumer. A single `AudioStream` per remote track SHALL serve both playback and VU metering. No separate `_tap_remote` task SHALL be created.

#### Scenario: Tap into Local Microphone Track
- **WHEN** the local microphone track is published
- **THEN** an `AudioStream` is attached to capture frames for mic level calculation

#### Scenario: Remote track VU sampled in playback pump
- **WHEN** a remote audio track is subscribed and the playback pump is active
- **THEN** the peak level of each played frame is sampled within the pump loop and reported via a callback; no separate AudioStream is opened for the remote track
