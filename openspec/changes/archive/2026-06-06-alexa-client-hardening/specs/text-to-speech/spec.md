## MODIFIED Requirements

### Requirement: Interchangeable TTS Backend
The system SHALL provide a modular architecture for text-to-speech, allowing different engines (local or cloud-based) to be used via a common interface. The Piper engine SHALL validate that the configured voice file exists and is loadable at `init_engine()` time. If the voice file is missing or fails to load, `init_engine()` SHALL log the error and fall back to the Pico engine rather than deferring the failure to the first `say()` call.

#### Scenario: Pico TTS supported
- **WHEN** the system is configured to use the Pico TTS backend
- **THEN** it generates localized speech using the `pico2wave` utility

#### Scenario: Piper voice validated at init
- **WHEN** `init_engine()` is called with a Piper voice path that does not exist on disk
- **THEN** an error is logged immediately and the engine falls back to Pico; no exception is raised at `say()` time

#### Scenario: Piper voice loaded successfully at init
- **WHEN** `init_engine()` is called with a valid Piper voice path
- **THEN** the voice is loaded once during init; subsequent `say()` calls use the already-loaded voice without re-opening the file
