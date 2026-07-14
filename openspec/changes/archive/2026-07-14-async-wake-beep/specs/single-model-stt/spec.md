# single-model-stt — Delta: async wake beep

## MODIFIED Requirements

### Requirement: Endpoint-gated matching with confirmation tone

The system SHALL act on a matched wake word or command only once the utterance is followed by silence (a VAD/endpoint event). On a confirmed match the system SHALL start playback of a "good tone" without blocking the recognition loop: tone playback and action dispatch SHALL proceed concurrently, and the recognition thread SHALL NOT wait for tone playback to finish before dispatching.

#### Scenario: Match confirmed on silence

- **WHEN** the transcript matches a wake word or command phrase
- **AND** the speaker stops (silence ≥ `stt.vad_silence_ms`) or the backend reports an endpoint
- **THEN** the system starts playback of the configured good tone
- **AND** proceeds to dispatch / wake-state handling without waiting for the tone to finish

#### Scenario: No tone before silence

- **WHEN** a partial transcript matches but speech is ongoing
- **THEN** no tone is emitted and no dispatch occurs until the endpoint

#### Scenario: Tone disabled

- **WHEN** `recognition.wake_tone` is `none`
- **THEN** no tone playback process is started
- **AND** dispatch proceeds immediately, identical to today's behavior

#### Scenario: Beep echo does not re-trigger recognition

- **WHEN** the good tone is playing while the microphone is capturing
- **THEN** the tone's acoustic echo is absorbed by the existing post-wake flush (`stt.flush_ms`) / playback-gate mechanisms
- **AND** the tone does not produce a transcript that matches a wake word or trigger
