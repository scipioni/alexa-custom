## Why

The voice assistant needs a rich conversational mode where the user can have a back-and-forth dialogue with an AI agent, rather than the single-turn wake-word → command → action flow. This enables complex interactions (multi-step reasoning, contextual follow-ups) that the trigger-based system cannot support. The agentic room was built and deployed; this change documents the existing implementation and addresses the key usability issue where the agent continues speaking past the desired answer.

## What Changes

- Document the existing agentic room implementation: `agent.py`, `agent_session` action, LiveKit room orchestration
- Fix the "talks too much" verbosity problem where the LLM generates responses longer than needed and/or the audio loop continues capturing unintended speech (echo, ambient noise)
- The architecture is already in production — this change captures design decisions and refines the interaction lifecycle

## Capabilities

### New Capabilities
- `agent-session`: LiveKit room-based conversational AI agent, triggered via the `agent_session` action type, using Vosk (STT) → Groq (LLM) → Piper (TTS)

### Modified Capabilities

<!-- No existing specs to modify -->

## Impact

- `agent.py` — standalone agent script (already deployed)
- `alexa_custom/actions.py` — `agent_session` action handler, `_create_agent_room`, `_generate_agent_tokens`
- Conf/actions/system.yaml — `"aiuto agente"` trigger wiring
- No dependency changes; relies on existing vosk, piper-tts, openai (Groq), livekit packages
