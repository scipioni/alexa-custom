## MODIFIED Requirements

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
