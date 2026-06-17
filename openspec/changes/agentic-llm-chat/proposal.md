## Why

The current `llm_chat` action is purely conversational — the LLM talks back but cannot trigger any system actions (MQTT, shell, volume, etc.). Users must exit the LLM conversation and issue a separate voice command to perform real-world actions. Making the LLM agentic — able to call tools and feed results back into the conversation — removes this friction and unlocks natural conversational control of the entire device surface.

## What Changes

- **New agentic wrapper** in `actions.py` that intercepts LLM replies, parses tool calls, dispatches to `ActionRegistry`, and feeds results back to the LLM for final response.
- **Tool definitions** auto-generated from the existing `ActionRegistry` handlers, exposed to the LLM via the OpenAI/Ollama `tools` API parameter.
- **`ConversationEngine`** gains optional tool-awareness: tool definitions injected into system messages, and a non-streaming mode for the tool-calling loop (streaming resumes for the final text).
- **Shell safety**: `shell` tool restricted to an allowlist of allowed commands.
- **Config update**: CrofAI API credentials and model selection in `conf/secrets.yaml` / `conf/config.yaml`.
- No changes to existing trigger/action dispatch — the agentic wrapper is a new action type, not a replacement.

## Capabilities

### New Capabilities
- `tool-calling`: Define JSON Schema tool definitions for all `ActionRegistry` handlers and expose them to the LLM via the native `tools` API parameter.
- `agentic-loop`: Execute tool call → dispatch → result → re-feed loop within `ConversationEngine`, then stream final text to TTS.
- `shell-allowlist`: Configurable allowlist of safe shell commands the LLM may execute, with parameter validation.

### Modified Capabilities
- `llm-chat` (existing `llm_chat` action): Updated to enable agentic mode via a new `handle_llm_chat_agentic` wrapper in `actions.py`. The original action is preserved.

## Impact

- `actions.py`: New agentic wrapper, tool definition generation, shell allowlist
- `llm.py`: `ConversationEngine` gains tool injection, non-streaming loop mode, and result re-feed; `OllamaClient`/`OpenAIClient` unchanged (native API already supports `tools`)
- `config.py`: No changes needed — existing `LLMConfig` and `OpenAIClient` path covers CrofAI
- `conf/secrets.yaml`: CrofAI API key and base URL
- `conf/config.yaml`: Optional tool allowlist config
- Tests: New `test_agentic_loop.py` for tool dispatch, allowlist, and integration with `ConversationEngine`
