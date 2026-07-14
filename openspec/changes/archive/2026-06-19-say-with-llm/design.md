## Context

The action registry (`actions.py`) already has two complementary action types:

- `say` — speaks a static (template-rendered) string via the TTS engine.
- `llm_chat` — enters an interactive multi-turn voice loop: listen → LLM → TTS → repeat.

Both use a cached `ConversationEngine` (keyed by host/model/lang/system_prompt) that holds conversation history. The missing primitive is a **one-shot LLM → TTS** path that can be wired to any trigger without requiring the user to interact further.

The LLM plumbing in `llm.py` already provides everything needed:
- `LLMClient.chat_stream()` — async token generator over an OpenAI-compatible endpoint.
- `ConversationEngine.reply_streaming()` — handles sentence splitting, streaming TTS callbacks, history append/commit, and `_UNREACHABLE` signalling.
- `get_engine(cfg, lang)` — returns the shared, cached engine instance.
- `_split_sentences()` — reusable sentence boundary splitter.

## Goals / Non-Goals

**Goals:**
- New `say-with-llm` action type that sends a one-shot prompt to the LLM and speaks the streaming reply.
- Optional `file` parameter: read text from disk and prepend it as context to the prompt.
- Template rendering on `prompt` (date, time, etc.) via existing `_render_text()`.
- Shared `ConversationEngine` session with `llm_chat` so the exchange enters conversation history.
- Graceful fallback: if LLM is not configured or unreachable, speak the resolved text (prompt + file content) literally via TTS.
- `max_chars` parameter to cap file content size (default 4000).
- `model` parameter to override the configured model per-action.

**Non-Goals:**
- Adding `say-with-llm` to the LearnWizard (deferred).
- Streaming file content in chunks larger than `max_chars` — hard cap only.
- Any new network dependency or TTS backend.

## Decisions

### Use `ConversationEngine.reply_streaming()` rather than calling `LLMClient` directly

**Decision**: delegate to the engine's `reply_streaming()` instead of inlining the token loop.

**Rationale**: `reply_streaming()` already handles sentence splitting, TTS callbacks, `_UNREACHABLE` detection, history append/commit, and context-window expiry. Duplicating that logic would create a maintenance surface. Calling the shared engine also satisfies the "join session" requirement at zero cost.

**Alternative considered**: instantiate a fresh `LLMClient` per call (no history). Rejected — loses the session-join requirement and duplicates streaming logic.

### Fallback: speak literally on missing config or `_UNREACHABLE`

**Decision**: if `actions_config.llm` is `None`, or if `reply_streaming` returns `_UNREACHABLE`, speak the resolved text directly through the TTS engine (same as a `say` action).

**Rationale**: Preserves utility even when Ollama is down. File content truncated to `max_chars` is already a reasonable length to narrate. For `_UNREACHABLE`, we speak the `prompt` (not the full file content, which could be large) to avoid an unexpectedly long fallback utterance.

**Alternative considered**: emit the error tone and stay silent. Rejected — degrades silently with no user feedback.

### `max_chars` caps file read, not the combined message sent to the LLM

**Decision**: `max_chars` limits how many characters are read from `file`. It does not truncate the `prompt`. The combined string (file + prompt) is sent to the LLM as-is.

**Rationale**: `prompt` is always user-authored and typically short. File content is the unbounded input. Keeping the cap on the file side makes the behaviour predictable.

### No new config keys — action params only

**Decision**: all per-invocation settings (`file`, `max_chars`, `model`, `lang`) live in the action's `params` dict in the YAML. No new top-level config section.

**Rationale**: These are call-site concerns, not daemon-wide settings. `llm.model` in `config.yaml` remains the default; the `model` param is an override.

## Risks / Trade-offs

- **History pollution from large files**: file content (up to `max_chars`) is stored in `ConversationEngine._history` as a user turn. With `context_turns: 10` and `max_chars: 4000`, worst case is ~40 KB in RAM. Acceptable given the context window timer eventually clears it.
- **LLM latency on a trigger path**: `say-with-llm` is synchronous from the user's perspective — the trigger fires and the user waits for the LLM to start streaming. For cold Ollama models this could be several seconds. Mitigated by the existing warmup call in `get_engine()`.
- **File read errors**: if `file` points to a missing or unreadable path, the action logs a warning and continues with only the `prompt`. This is intentional graceful degradation.
- **No streaming cancellation**: if the user activates a wake word while `say-with-llm` is streaming, the STT gate prevents a new command from firing until TTS finishes. This is existing behaviour shared with `llm_chat` and `say`.
