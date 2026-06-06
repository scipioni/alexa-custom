## MODIFIED Requirements

### Requirement: say action type
The system SHALL support a `say` action type that converts text to audible speech through the PipeWire default sink. For the Piper backend, audio SHALL be streamed sentence-by-sentence via `paplay --raw` stdin rather than played from a pre-rendered WAV file.

#### Scenario: Assistant speaks to user
- **WHEN** a `say` action is executed with the text "Chiamo subito"
- **THEN** the system generates the audio and plays it; for the Piper backend this is via `paplay --raw`, with `aplay -D pipewire` as fallback if `paplay` is absent
