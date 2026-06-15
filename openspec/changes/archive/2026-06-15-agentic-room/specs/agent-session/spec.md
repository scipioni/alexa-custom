## ADDED Requirements

### Requirement: Trigger agent session from voice command
The system SHALL create an ephemeral LiveKit room and spawn an AI agent process when the user says "aiuto agente" or a configured trigger phrase.

#### Scenario: User triggers agent session via voice
- **WHEN** the user says the wake word followed by a trigger phrase that maps to an `agent_session` action
- **THEN** the system creates a new LiveKit room via the LiveKit API with a 5-minute empty timeout
- **AND** generates separate JWT tokens for the user (with microphone publish permission) and the agent
- **AND** spawns `agent.py` as a subprocess with `--room`, `--token`, and `--url` arguments
- **AND** opens the user's browser to a `meet.livekit.io/custom/` URL with the user token

### Requirement: Agent processes audio through LiveKit stream
The agent SHALL listen for audio tracks published by participants in the room and perform speech-to-text, LLM inference, and text-to-speech in sequence.

#### Scenario: Agent receives and responds to speech
- **WHEN** a participant joins and publishes an audio track
- **THEN** the agent subscribes to the audio track via LiveKit's `track_subscribed` event
- **AND** decodes audio frames through Vosk `KaldiRecognizer` at 16 kHz
- **AND** when Vosk produces a final result with non-empty text, sends it to the Groq LLM (`llama-3.1-8b-instant`, `max_tokens=200`)
- **AND** speaks the LLM's response via Piper TTS through the agent's own LiveKit audio source

#### Scenario: Agent plays greeting beep on connect
- **WHEN** the agent connects to the room and publishes its audio track
- **THEN** it plays a 660 Hz beep (0.3 seconds) followed by "Ciao, sono il tuo assistente. Come posso aiutarti?"

### Requirement: Conversation history management
The agent SHALL maintain a multi-turn conversation history with bounded context.

#### Scenario: Conversation context is trimmed
- **WHEN** the conversation exceeds 12 total messages (system + user + assistant)
- **THEN** the history is trimmed to system prompt + the last 10 messages (5 user/assistant turns)

### Requirement: Conversation lifecycle
The agent session SHALL terminate when the participant leaves or after 180 seconds of inactivity.

#### Scenario: Agent disconnects on participant leave
- **WHEN** the participant disconnects from the room
- **THEN** the `stop_event` is set, the audio stream loop breaks, and the agent disconnects

#### Scenario: Agent disconnects on timeout
- **WHEN** 180 seconds elapse without the participant disconnecting
- **THEN** the agent disconnects due to asyncio timeout

### Requirement: Agent response verbosity control
The agent's LLM-generated speech SHALL be concise. The system prompt and `max_tokens` SHALL constrain response length, and the agent SHALL NOT re-respond to its own TTS output (echo prevention).

#### Scenario: Agent response is constrained by system prompt
- **WHEN** the agent sends the user's text to the LLM
- **THEN** the system prompt instructs the model to respond in massimo due frasi (maximum two sentences) and always in Italian

#### Scenario: Agent does not respond to its own speech via echo
- **WHEN** the agent finishes speaking its TTS response
- **THEN** it SHALL NOT treat any audio that may contain the tail of its own speech (picked up via the participant's microphone) as a new user utterance
- **AND** Vosk partial/final recognitions that occur within a cooldown window after TTS playback SHALL be discarded
