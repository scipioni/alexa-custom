## Why

The `llm_chat` action is a capable multi-turn conversation engine backed by the existing `ConversationEngine` class. But it lives in a separate reality from the rest of the system — the LLM can talk about anything but cannot *do* anything. Currently, to toggle a light the user must exit the conversation and utter a specific trigger phrase. This forces users to memorise trigger patterns and breaks the conversational flow.

With a ReAct-style tool-calling loop, the LLM can autonomously decide to invoke `mqtt_publish`, `shell`, `set_volume`, or other system tools, receive their outputs, and compose a final reply. The same voice conversation becomes an agent capable of affecting the real world.

## What Changes

Introduce an agentic tool-calling loop inside `ConversationEngine`. The LLM receives tool schemas (via system prompt or native API), chooses when to call a tool, gets the result appended to context, and continues reasoning until it produces a final answer.

### Five tools defined

| Tool | Purpose | Already exists as action |
|------|---------|------------------------|
| `shell` | Run a whitelisted shell command | `actions.py:handle_shell` |
| `mqtt_publish` | Publish to MQTT topic | `actions.py:handle_mqtt_publish` |
| `set_volume` | Set system volume 0–100 | `actions.py:handle_set_volume` |
| `get_state` | Read device/system variable | new |
| `get_datetime` | Current local date/time/timezone | new |

### Backend: Crof AI (OpenAI-compatible)

Crof AI exposes a standard `/v1/chat/completions` REST API. The existing `OpenAIClient` in `llm.py` handles it with `backend: openai`, host `https://ai.nahcrof.com`, and a Crof API key.

Since the Crof API (like OpenAI) has no native `<tool_call>` semantics, the integration uses **prompted JSON via system prompt injection** — tool schemas are embedded in the system prompt and the model emits `<tool_call>...</tool_call>` blocks when it wants to invoke a tool. This works with any OpenAI-compatible endpoint including Crof, Ollama, or OpenAI itself.

### Configuration
```yaml
llm:
  backend: openai
  host: https://ai.nahcrof.com
  model: greg-2-super
  api_key: sk-your-crof-key
  tool_calling: true
```

### Modified capabilities

- **llm-conversation**: Extended with tool-calling loop, tool schema registry, and safety validation
- **action-dispatch**: New `tool_executor` module that reuses existing action handler infrastructure

### Files affected

| File | Change |
|------|--------|
| `alexa_custom/llm.py` | Tool registry, agentic loop in `ConversationEngine`, JSON tool-call parser |
| `alexa_custom/actions.py` | Minor — expose existing `handle_shell`, `handle_mqtt_publish`, `handle_set_volume` as callable tool handlers |
| `alexa_custom/config.py` | Add `tool_calling_mode` flag to `LLMConfig`, `max_tool_cycles`, shell command whitelist |
| `alexa_custom/mqtt.py` | Minor — expose allowed topic patterns for tool validation |

### Not affected

- STT, audio, wake-word detection, web dashboard, LiveKit, display
- Existing `llm_chat` action behaviour when tool-calling is disabled
