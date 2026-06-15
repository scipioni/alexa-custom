## Context

The agentic room provides a conversational AI experience triggered from the voice assistant's wake-word flow. It is a separate process (`agent.py`) that joins a LiveKit room as an AI agent, listens for participant speech via Vosk, reasons via Groq (Llama 3.1 8B), and responds via Piper TTS. The user interacts through a browser tab opened to `meet.livekit.io/custom/`.

The main usability issue is that the agent "talks too much" — the LLM generates responses longer than the user wants, and the perpetual listening loop can pick up echo from the participant's browser, creating cascading unwanted replies.

## Goals / Non-Goals

**Goals:**
- Document the existing agent-session architecture
- Fix the verbosity problem so the agent stops at the desired answer
- Prevent echo-induced re-triggering after TTS playback

**Non-Goals:**
- Replace the main daemon's existing `llm_chat` action
- Add wake-word gating to the agent room (it's inherently always-on within the session)
- Support multiple concurrent agent rooms

## Decisions

### Decision: Separate process vs in-process agent
The agent runs as a `subprocess.Popen` of `agent.py` rather than as an async task in the main daemon. This isolates the agent process (LLM/TTS memory) from the main daemon's audio pipeline and allows independent lifecycle management.

### Decision: Groq as LLM backend (hardcoded)
The agent uses Groq's `llama-3.1-8b-instant` via the AsyncOpenAI client with hardcoded credentials (`GROQ_API_KEY` env var). This was chosen for low-latency streaming inference. The main daemon's `OpenAIClient` (which supports any OpenAI-compatible endpoint) could be reused but is not.

### Decision: Vosk full-vocabulary mode
Unlike the main daemon's grammatically constrained Vosk usage, `agent.py` uses a free-vocabulary `KaldiRecognizer` (no grammar restriction). This allows the agent to recognize arbitrary conversational speech but may produce more false-positive activations from ambient noise or TTS echo.

### Decision: Piper runs synchronously in thread
TTS synthesis runs in `loop.run_in_executor(None, _synthesize, ...)` and the full PCM is buffered before playback begins. No streaming TTS — the entire response is generated, then played as a single contiguous audio block.

## Risks / Trade-offs

[Echo re-triggering] → The agent has no post-TTS cooldown. Audio from the participant's browser microphone that picks up the TTS speaker output will be captured by LiveKit, streamed to the agent, recognized by Vosk, and sent to the LLM as a new turn. Mitigation: introduce a `cooldown_until` timestamp after `_speak()` that skips Vosk results for a configurable window (e.g. 500ms past TTS end).

[Verbose LLM responses] → `max_tokens=200` allows ~150 words, much more than the "massimo due frasi" system prompt requests. Mitigation: reduce `max_tokens` to 80-100 and/or strengthen the system prompt with a word count limit.

[No echo cancellation] → The agent operates inside LiveKit where the participant's browser applies its own AEC, but the agent itself has no echo handling. If the browser's AEC is imperfect, the agent hears itself.
