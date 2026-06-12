## ADDED Requirements

### Requirement: Streaming TTS respects system output volume linearly

The Piper streaming TTS path SHALL produce audio at the system's output volume level, without applying any additional software scaling. The single source of truth for volume SHALL be the PipeWire sink volume set via `wpctl set-volume`. The TTS streaming path SHALL NOT apply its own volume multiplication.

#### Scenario: TTS plays back at current volume setting
- **WHEN** the system output volume is set to 0.75
- **AND** `PiperTTS.say()` is called with a text to speak
- **THEN** the audio output level matches the 0.75 volume setting linearly (not quadratically)

#### Scenario: TTS volume changes with slider
- **WHEN** the user adjusts the web volume slider from 50% to 25%
- **AND** TTS speech is playing at the same time
- **THEN** the speech volume changes immediately to match the new 25% level

#### Scenario: TTS is not quieter than tones at same volume
- **WHEN** the system output volume is set to any value
- **AND** a tone is played
- **AND** the same volume setting is used for TTS speech
- **THEN** the perceived loudness of TTS matches the tone at equal volume settings

## REMOVED Requirements

### Requirement: Piper streams audio sentence-by-sentence via paplay (subsumed by corrected volume behavior)
**Reason**: The original spec correctly describes the streaming behavior. The volume behavior is now specified by the ADDED requirement above. No existing streaming behavior is removed.
**Migration**: No migration needed. The streaming mechanism is unchanged.
