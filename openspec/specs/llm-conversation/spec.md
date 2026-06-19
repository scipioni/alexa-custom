# Capability: LLM Conversation

## Purpose
Provide rich, contextual, multi-turn conversation and intelligent unmatched-command routing via remote Ollama endpoints.

## Requirements

### Requirement: Free-form voice conversation via Ollama
The system SHALL support a `ConversationEngine` that sends user utterances to a remote Ollama instance and speaks the reply via TTS. The engine SHALL only be active when `llm:` is present in `config.yaml`. The system prompt SHALL instruct the model to reply in plain prose suitable for TTS (no markdown, no lists, no special characters) in the language specified by the active wake word group's `lang` field (default `it-IT`).

#### Scenario: Unmatched command routed to LLM
- **WHEN** a wake word is detected, a command is transcribed, no trigger matches, and `llm.fallback_on_no_match` is `true`
- **THEN** the transcript is sent to Ollama and the response is spoken via TTS

#### Scenario: LLM not configured
- **WHEN** `config.yaml` contains no `llm:` key
- **THEN** unmatched commands play the timeout tone as before and the LLM code is never invoked

#### Scenario: LLM unreachable
- **WHEN** the Ollama host is unreachable or the request times out
- **THEN** the system speaks "agente remoto non raggiungibile" and returns to wake-word listening

#### Scenario: Language follows wake word group
- **WHEN** the active wake word group has `lang: en-US`
- **THEN** the system prompt instructs the model to reply in English

### Requirement: Rolling conversation history with time-windowed reset
The `ConversationEngine` SHALL maintain a rolling history of the last `context_turns` user/assistant exchange pairs (default 10). The history SHALL be cleared if the elapsed time since the last interaction exceeds `context_window_secs` (default 60). A new interaction always appends to the current history before sending to the LLM. History is shared across all action types that use the same engine instance — including both `llm_chat` and `say-with-llm`.

#### Scenario: Follow-up question uses prior context
- **WHEN** the user asks "chi è Einstein?" and then (within 60 s) asks "quanti anni aveva?"
- **THEN** the second request includes the prior exchange so the model can resolve "aveva" in context

#### Scenario: Long pause clears history
- **WHEN** more than `context_window_secs` seconds pass between two utterances
- **THEN** the second utterance is sent with an empty history (fresh conversation)

#### Scenario: History capped at context_turns
- **WHEN** more than `context_turns` exchanges have occurred
- **THEN** only the most recent `context_turns` pairs are included in the LLM request

#### Scenario: say-with-llm turn enters shared history
- **WHEN** a `say-with-llm` action fires and the LLM replies successfully
- **THEN** the prompt (user turn) and reply (assistant turn) are recorded in the same `ConversationEngine` history used by `llm_chat`, so a subsequent `llm_chat` session can reference them

### Requirement: `llm_chat` action type for explicit LLM conversation
The system SHALL support a `llm_chat` action type that enters the `ConversationEngine` loop directly. An optional `system_prompt` parameter in the action overrides the global system prompt for that invocation.

#### Scenario: Explicit llm_chat trigger
- **WHEN** a trigger with `type: llm_chat` is dispatched
- **THEN** the system enters a multi-turn conversation loop using the active `ConversationEngine`

#### Scenario: Per-trigger system prompt override
- **WHEN** an `llm_chat` action specifies `system_prompt: "Sei un esperto di cucina"`
- **THEN** that prompt is used for this conversation session instead of the global one

### Requirement: Thinking tone before LLM response
The system SHALL play a brief audio tone (name: `info`) after receiving the user utterance and before the Ollama response arrives, to signal that the system is processing.

#### Scenario: Tone plays during LLM latency
- **WHEN** an utterance is routed to the LLM
- **THEN** the `info` tone plays immediately, before the network request completes
