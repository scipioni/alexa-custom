## Context

The current `ConversationEngine` (`llm.py:227`) provides `reply_streaming()` which:
1. Builds messages (system prompt + history + user text)
2. Streams tokens from the LLM via `chat_stream()`
3. Splits sentences and speaks each via TTS in real-time
4. Commits the full reply to `_history`

There is no mechanism for the LLM to call tools. The system has existing action handlers (`handle_shell`, `handle_mqtt_publish`, `handle_set_volume` in `actions.py`) that are only reachable via trigger-phrase dispatch — not from within a conversation.

### Key constraint from the existing codebase

The `reply_streaming()` method speaks *as it receives tokens*. An agentic loop cannot stream — it must collect the full response, inspect it for tool calls, execute tools, and loop. This means a separate non-streaming path is required.

### Backend constraint

The primary backend is Crof AI — an OpenAI-compatible API (`/v1/chat/completions`). It's accessed via the existing `OpenAIClient` with `backend: openai`, host `https://ai.nahcrof.com`, and an API key. The codebase also supports Ollama (`OllamaClient`) as a secondary option.

All three (Crof, OpenAI, Ollama) use plain `messages: list[dict]` with `role`/`content` fields. None have reliable native tool-calling in the deployed versions. The design therefore uses **prompted JSON** as the single mode — tool schemas are injected into the system prompt and the model emits `<tool_call>...</tool_call>` blocks.

## Goals / Non-Goals

**Goals:**
- LLM can invoke `shell`, `mqtt_publish`, `set_volume`, `get_state`, `get_datetime` during a conversation
- Tool results are fed back to the LLM; it uses them to compose the final answer
- Existing non-agentic `llm_chat` behaviour is preserved when tool-calling is disabled
- Tool execution is safe: shell whitelist, topic validation, input clamping
- Configurable max loop iterations (default 5) to prevent infinite loops

**Non-Goals:**
- Parallel tool execution (each tool call is sequential within the loop)
- Frontend feedback for tool-calling steps (the user only hears the final answer)
- Streaming of intermediate reasoning
- Support for arbitrary LLM provider APIs beyond the current OpenAI-compatible clients (Crof, OpenAI, Ollama)

## Decisions

### D1: Non-streaming agentic method — `reply_agentic()`

**Chosen:** Add `async def reply_agentic(self, user_text: str) -> str` to `ConversationEngine`. It uses `_client.chat()` (non-streaming, already exists on both clients). The existing `reply_streaming()` is unchanged.

```
User turn enters here
  │
  ▼
reply_agentic(user_text)
  │
  ├── cycle 1: client.chat(messages) ──► tool call? ──► execute ──► append result ──► continue
  ├── cycle 2: client.chat(messages) ──► tool call? ──► execute ──► append result ──► continue
  ├── ...
  └── cycle N: client.chat(messages) ──► no tool call ──► return final answer
```

The `handle_llm_chat` action in `actions.py` checks `cfg.tool_calling`:
- `False` → calls `engine.reply_streaming()` (current behaviour, speaks each sentence)
- `True` → calls `engine.reply_agentic()`, speaks the final answer once via TTS

**Rationale:** Keeps the streaming path untouched. The agentic loop is inherently non-streaming (can't speak tool calls as they're generated). Separation of concerns — each method does one thing.

### D2: Tool schema registry — format-agnostic

**Chosen:** A `ToolRegistry` class in `llm.py` that stores `ToolSchema` objects and serializes to a JSON string for system prompt injection.

```python
@dataclass
class ToolParameter:
    name: str
    type: str           # "string" | "integer" | "number" | "boolean"
    description: str
    required: bool = True
    enum: list[str] | None = None   # for constrained values
    minimum: float | None = None
    maximum: float | None = None

@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: list[ToolParameter]
    handler: Callable

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSchema] = {}

    def register(self, schema: ToolSchema) -> None: ...

    def to_system_prompt_block(self) -> str:
        """Serialize all tools as JSON for injection into system prompt."""

    def execute(self, name: str, arguments: dict) -> dict:
        """Execute a tool, return normalized result."""
```

**Rationale:** Format-agnostic by design. The `to_system_prompt_block()` produces a JSON string that's injected into the system prompt. If the backend later supports native tool schemas, a separate serializer method can produce that format. The registry itself doesn't depend on any API convention.

### D3: JSON tool-call detection with `<tool_call>` delimiter

**Chosen:** The system prompt instructs the model to emit tool calls as:
```
<tool_call>
{"name": "shell", "arguments": {"command": "echo hello"}}
</tool_call>
```

Parser in `ConversationEngine._parse_tool_call(text) -> ToolCall | None`:
- Regex `<tool_call>\s*(\{.*?\})\s*</tool_call>` with `re.DOTALL`
- Parse matched JSON, validate name + arguments against registry
- If no match or invalid JSON → `None` (treat as final answer)

**Rationale:** The `<tool_call>` delimiter makes parsing reliable even when the model wraps the JSON in natural language. The delimiter is case-sensitive and must be on its own line in system prompt instructions.

If multiple `<tool_call>` blocks appear in one response, only the first is executed per cycle. This keeps the loop simple and prevents runaway tool chains.

### D4: Tool result format — normalized return type

All tools return:
```python
{"success": bool, "output": Any, "error": str | None}
```

The result is serialized to JSON and appended to messages as a `"tool"` role:
```python
messages.append({"role": "assistant", "content": response_text_with_tool_call})
messages.append({"role": "tool", "content": json.dumps(result)})
```

If the backend doesn't support `"tool"` role, fall back to:
```python
messages.append({"role": "user", "content": f"Tool '{tool_name}' returned: {json.dumps(result)}"})
```

**Rationale:** Normalized format lets the LLM handle both success and failure uniformly. The `"tool"` role is preferred (cleaner semantics) with `"user"` fallback.

### D5: Shell command safety

**Chosen:** A whitelist of allowed command prefixes in `LLMConfig.shell_whitelist`. Reject immediately if the command doesn't start with any whitelisted prefix.

```yaml
llm:
  shell_whitelist:
    - "echo "
    - "cat /proc/"
    - "df -h"
    - "free -h"
    - "uptime "
    - "uname "
    - "ls /sys/class/thermal/"
```

Execution uses `asyncio.create_subprocess_shell()` with `shlex.quote()` on arguments.

**Rationale:** Prefix whitelisting is simpler and more auditable than regex or allowlist of characters. The `shell` tool is inherently dangerous — the whitelist is conservative. Users can expand it by editing config.

### D6: Config additions

Extended `LLMConfig` in `config.py`:

```python
@dataclass
class LLMConfig:
    # ... existing fields ...
    tool_calling: bool = False
    max_tool_cycles: int = 5
    tool_calling_mode: str = "prompted_json"  # reserved for future native mode
    shell_whitelist: list[str] = field(default_factory=lambda: [
        "echo ",
        "cat /proc/",
        "df -h",
        "free -h",
        "uptime ",
        "uname ",
        "ls /sys/class/thermal/",
    ])
    mqtt_allowed_topics: list[str] = field(default_factory=list)
```

**Rationale:** `tool_calling: false` by default — opt-in. This ensures existing setups are unaffected.

### D7: Tool implementation sources

Rather than duplicating logic, tool handlers are thin wrappers that reuse existing infrastructure:

| Tool | Impl Source | Notes |
|------|-------------|-------|
| `shell` | New `_tool_shell()` in `llm.py` | Uses same `asyncio.create_subprocess_shell` as `handle_shell` |
| `mqtt_publish` | `ActionContext.mqtt_client.publish` | Passed from `handle_llm_chat` to `reply_agentic` |
| `set_volume` | `audio_hw.set_output_volume` | Also calls `pulse_session` + `save_volume_config` |
| `get_state` | New `_tool_get_state()` in `llm.py` | Reads from `_read_system_vitals()` in `actions.py` |
| `get_datetime` | New `_tool_get_datetime()` in `llm.py` | Returns `datetime.now().isoformat()` + `tzname` |

The `mqtt_client` and other dependencies are threaded through via `ActionContext` — already available in `handle_llm_chat`.

### D8: Tool calls excluded from `_history`

Tool turns (tool call + result messages) are appended only to the working `messages` list within the agentic loop — not to `_history`. After the loop completes, only the final assistant reply is committed via `_commit()`.

**Rationale:** Keeps conversation history clean and compact. Tool results can be large (file contents, complex state), and including them in history would consume the context window on every future turn.

## Risks / Trade-offs

- **Non-streaming latency**: The user must wait for the entire agentic loop (multiple LLM calls) before hearing anything. A typical 2-tool interaction adds 2–6 seconds of silence. Mitigation: play a brief "thinking" tone at the start of `reply_agentic()` to signal activity.
- **Token cost**: Each tool-calling cycle adds tokens (tool call text + result). A 5-cycle loop could consume significant context. Mitigation: `max_tool_cycles` default 5; keep results concise.
- **Shell injection**: Even with prefix whitelisting, creative argument construction could be dangerous. Mitigation: `shlex.quote()` on all arguments; whitelist is conservative; all invocations are logged.
- **Model compliance**: The LLM may not follow the `<tool_call>` format reliably. Mitigation: retry with a firmer reminder in the system prompt if parsing fails; fall back to "I'm sorry, I encountered an error" after N failed parsing attempts.
- **Crof API compatibility**: If Crof AI changes its API format or adds native tool-calling, the current `OpenAIClient` may need updates. Mitigation: the `tool_calling_mode` config flag (`"prompted_json"` / `"native"`) provides a clean switch point without changing `ConversationEngine`.

## Migration Plan

1. Add `ToolSchema`, `ToolParameter`, `ToolRegistry` dataclasses to `llm.py`
2. Implement tool call JSON parser (`_parse_tool_call`) in `ConversationEngine`
3. Implement `reply_agentic()` method with agentic loop
4. Register tool handlers: `shell`, `mqtt_publish`, `set_volume`, `get_state`, `get_datetime`
5. Extend `LLMConfig` with tool-calling fields, add parsing in `config.py`
6. Update `handle_llm_chat` to call `reply_agentic()` when `tool_calling=True`
7. Wire shell whitelist, topic validation, input clamping into tool executors
8. Add logging for all tool invocations
9. Test with a real Crof AI instance: multi-turn, tool call, context persistence

## Open Questions

- Should tool results be stored in `_history` or omitted? (Design says omit — D8. Revisit if users report confusion from the LLM forgetting what it just did.)
- Should we play a "tool executing" tone or stay silent? (Defer — stay silent for v1, the tone would confuse users.)
- How should multi-line shell output be rendered for the LLM? (Truncate to 1000 chars for now.)
