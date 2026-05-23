## ADDED Requirements

### Requirement: say action type
The system SHALL support a `say` action type in the trigger sequence. This action converts a provided `text` parameter into audible speech using the configured TTS backend.

#### Scenario: Sequence with voice feedback
- **WHEN** a trigger defines multiple actions starting with `say`
- **THEN** the system speaks the text first, then proceeds to subsequent actions (e.g., telegram or livekit_join)
