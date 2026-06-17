## ADDED Requirements

### Requirement: Agentic loop dispatches tool calls
When the LLM responds with `tool_calls`, the system SHALL execute each sequentially via the `ActionRegistry` and feed the results back as `tool` role messages before requesting the next LLM completion.

#### Scenario: Single tool call
- **WHEN** the LLM responds with one `tool_call` (e.g. `mqtt_publish` with topic and payload)
- **THEN** the system SHALL execute the tool via `ActionRegistry.execute()`, feed the result back to the LLM as a `tool` role message, and continue the conversation

#### Scenario: Multiple tool calls
- **WHEN** the LLM responds with multiple `tool_calls` in one response
- **THEN** the system SHALL execute each sequentially, feeding each result back as a separate `tool` role message

#### Scenario: Mixed tool call and text response
- **WHEN** the LLM responds with both `tool_calls` and text `content`
- **THEN** the system SHALL execute the tools first, then include the text in the final response after all tool results are incorporated

### Requirement: Maximum tool call iterations
The system SHALL enforce a maximum of 5 tool-calling iterations per user turn to prevent infinite loops.

#### Scenario: Iteration limit reached
- **WHEN** the LLM has called tools 5 times without producing a final text response
- **THEN** the system SHALL stop the loop and speak "Non riesco a completare l'operazione" (or equivalent)

#### Scenario: Normal completion within limit
- **WHEN** the LLM calls tools 2 times and then produces a text response
- **THEN** the system SHALL stream the text to TTS and return

### Requirement: Final text streamed to TTS
After tool calls resolve and the LLM produces a final text-only response, the system SHALL stream it to TTS sentence by sentence, matching the existing `reply_streaming` behavior.

#### Scenario: Tool then speech
- **WHEN** the LLM calls `mqtt_publish`, gets success, then responds "Ho acceso la luce"
- **THEN** the system SHALL speak "Ho acceso la luce" via TTS

### Requirement: Tool error recovery
When a tool call fails (unreachable service, invalid params, etc.), the system SHALL feed the error message back to the LLM so it can respond appropriately.

#### Scenario: Tool failure with error result
- **WHEN** `mqtt_publish` fails because the broker is unreachable
- **THEN** the error result SHALL be returned to the LLM, and the LLM SHALL respond with an apology (e.g. "Mi dispiace, non riesco a connettermi")
