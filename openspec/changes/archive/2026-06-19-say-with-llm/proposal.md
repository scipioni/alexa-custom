## Why

The assistant can already hold a multi-turn conversation (`llm_chat`) or speak static text (`say`), but there is no way to fire a one-shot LLM query from a trigger and hear the result — useful for things like "read and summarise this file", "tell me something interesting", or composing dynamic announcements. Adding `say-with-llm` fills that gap without any new infrastructure.

## What Changes

- New `say-with-llm` action type registered in `actions.py`.
- Accepts `prompt` (template-rendered), `file` (path, read up to `max_chars`), `lang`, `max_chars` (default 4000), and `model` (optional override) parameters.
- Reuses the cached `ConversationEngine` (shared session with `llm_chat`), so the spoken exchange enters conversation history.
- Streams LLM output sentence-by-sentence through the existing TTS engine exactly as `llm_chat` does.
- Falls back to speaking the text literally if the LLM is not configured or unreachable at runtime.
- Prompt text is rendered through `_render_text()` (supports `{date}`, `{time}`, etc.).

## Capabilities

### New Capabilities

- `llm-say-action`: One-shot LLM → TTS action with optional file-content injection and graceful fallback to literal speech.

### Modified Capabilities

- `llm-conversation`: The `ConversationEngine` session is now shared between `llm_chat` and `say-with-llm`, so file-narration turns appear in conversation history alongside interactive turns.

## Impact

- **`alexa_custom/actions.py`**: new ~40-line handler; imports `_split_sentences` and `get_engine` from `llm.py`.
- **`alexa_custom/llm.py`**: no changes; existing symbols are reused.
- **`alexa_custom/config.py`**: no changes required.
- **No new dependencies**.
