## ADDED Requirements

### Requirement: Independent parec audio capture path for STT
The audio subsystem SHALL support a second independent microphone capture path using a `parec` subprocess at 16 kHz alongside the existing livekit `AudioStream` tap used for VU meters. The two paths MUST NOT interfere with each other.

#### Scenario: Both paths active simultaneously
- **WHEN** a LiveKit session is active and wake word detection is running
- **THEN** VU meters update via `AudioStream` tap and Vosk receives audio via `parec` concurrently without errors

#### Scenario: parec path active without LiveKit
- **WHEN** no LiveKit session is active
- **THEN** `parec` continues capturing and Vosk continues listening for wake words
