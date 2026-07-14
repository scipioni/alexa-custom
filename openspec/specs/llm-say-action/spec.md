# Capability: LLM Say Action

## Purpose

Support a `say-with-llm` action type that sends a one-shot prompt to the configured LLM and speaks the streaming reply via TTS, optionally injecting file content into the prompt. The exchange is recorded in the shared conversation history.

## Requirements

### Requirement: say-with-llm action type
The system SHALL support a `say-with-llm` action type that sends a one-shot prompt to the configured LLM and speaks the streaming reply via TTS. The action SHALL reuse the cached `ConversationEngine` so the exchange is recorded in the shared conversation history. The action SHALL NOT enter a listening loop; it completes after the reply has been fully spoken.

#### Scenario: Basic prompt spoken via LLM
- **WHEN** a trigger fires a `say-with-llm` action with `prompt: "Dimmi una curiosità scientifica"`
- **THEN** the prompt is sent to the LLM and the streaming reply is spoken sentence-by-sentence through TTS

#### Scenario: Reply enters conversation history
- **WHEN** a `say-with-llm` action completes successfully
- **THEN** the user turn (prompt) and assistant turn (reply) are stored in the shared `ConversationEngine` history, available to subsequent `llm_chat` interactions

### Requirement: File content injection
The system SHALL support a `file` parameter on `say-with-llm` that reads text from the specified path and prepends it to the prompt before sending to the LLM. At most `max_chars` characters SHALL be read from the file (default 4000). If the file cannot be read, the system SHALL log a warning and continue with only the prompt.

#### Scenario: File content prepended to prompt
- **WHEN** a `say-with-llm` action specifies `file: /home/scipio/notes.txt` and `prompt: "Riassumi in tre frasi"`
- **THEN** the file content (up to `max_chars` chars) is prepended to the prompt and the combined text is sent to the LLM

#### Scenario: File missing — graceful degradation
- **WHEN** a `say-with-llm` action specifies a `file` path that does not exist
- **THEN** a warning is logged and the action proceeds using only the `prompt`

#### Scenario: File-only (no prompt)
- **WHEN** a `say-with-llm` action specifies `file` but no `prompt`
- **THEN** the file content alone is sent to the LLM as the user turn

#### Scenario: max_chars caps file read
- **WHEN** the file at the specified path contains more than `max_chars` characters
- **THEN** only the first `max_chars` characters are read; the remainder is silently discarded

### Requirement: Template rendering on prompt
The system SHALL apply `_render_text()` template rendering to the `prompt` parameter before sending it to the LLM, supporting `{date}`, `{time}`, and any other tokens supported by the existing `say` action.

#### Scenario: Date token in prompt
- **WHEN** a `say-with-llm` action has `prompt: "Cosa succede il {date} nella storia?"`
- **THEN** `{date}` is replaced with the current date before the prompt is sent to the LLM

### Requirement: Per-action model override
The system SHALL support a `model` parameter on `say-with-llm` that overrides `llm.model` from the global config for that invocation only.

#### Scenario: model param overrides config
- **WHEN** a `say-with-llm` action specifies `model: mistral:7b`
- **THEN** that model is used for this call, regardless of the global `llm.model` setting

### Requirement: Fallback to literal TTS when LLM unavailable
The system SHALL fall back to speaking the resolved text literally (via the standard TTS engine) when the LLM is not configured or is unreachable at runtime.

#### Scenario: LLM not configured
- **WHEN** `config.yaml` contains no `llm:` key and a `say-with-llm` action fires
- **THEN** the resolved text (file content + prompt, or whichever is present) is spoken literally through TTS

#### Scenario: LLM unreachable at runtime
- **WHEN** the LLM endpoint is unreachable and `reply_streaming` returns `_UNREACHABLE`
- **THEN** the rendered `prompt` text is spoken literally through TTS (file content is not re-spoken to avoid an unexpectedly long fallback)

#### Scenario: No text available — silent no-op
- **WHEN** neither `prompt` nor `file` produces any text (both absent or empty)
- **THEN** the action completes silently without calling TTS
