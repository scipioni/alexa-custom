# Capability: Text-to-Speech

## Purpose
Provide audible voice feedback to the user via interchangeable TTS engines.

## Requirements

### Requirement: Interchangeable TTS Backend
The system SHALL provide a modular architecture for text-to-speech, allowing different engines (local or cloud-based) to be used via a common interface.

#### Scenario: Pico TTS supported
- **WHEN** the system is configured to use the Pico TTS backend
- **THEN** it generates localized speech using the `pico2wave` utility

### Requirement: say action type
The system SHALL support a `say` action type that converts text to audible speech through the PipeWire default sink.

#### Scenario: Assistant speaks to user
- **WHEN** a `say` action is executed with the text "Chiamo subito"
- **THEN** the system generates the audio and plays it via `pw-play` or `aplay`

### Requirement: STT Gating during speech
The system SHALL automatically pause the microphone recognition pipeline while the assistant is speaking to prevent acoustic feedback and self-triggering.

#### Scenario: Mic paused during TTS
- **WHEN** a `say` action starts playback
- **THEN** the STT recognizer is gated and remains paused until the speech ends
