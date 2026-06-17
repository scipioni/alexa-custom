## 1. Tool schema dataclasses and registry

- [x] 1.1 Add `ToolParameter`, `ToolSchema`, and `ToolCall` dataclasses to `alexa_custom/llm.py`
- [x] 1.2 Implement `ToolRegistry` class with `register()`, `get()`, `list_schemas()`, `execute()` methods
- [x] 1.3 Implement `ToolRegistry.to_system_prompt_block()` that serializes all tools as a JSON string for prompt injection
- [x] 1.4 Implement `ToolRegistry.execute()` that dispatches to the handler registered for a tool name and returns normalized `{success, output, error}`

## 2. Tool call JSON parser

- [x] 2.1 Implement `ConversationEngine._parse_tool_call(text: str) -> ToolCall | None` using regex `<tool_call>...</tool_call>`
- [x] 2.2 Add validation: parsed JSON must have `name` (str) and `arguments` (dict); name must match a registered tool
- [x] 2.3 Add retry logic: if parsing fails, append a reminder message and call the LLM again (up to 2 retries)
- [x] 2.4 Add `_format_tool_result(tool_name: str, result: dict) -> dict` that creates the message dict with `role: "tool"` (or `"user"` fallback)

## 3. Agentic loop — `reply_agentic()`

- [x] 3.1 Implement `async def reply_agentic(self, user_text: str, tool_registry: ToolRegistry, mqtt_client=None, actions_config=None) -> str` on `ConversationEngine`
- [x] 3.2 Build the agentic loop:
  - Prepare messages with `_prepare_messages()` + append tool schemas to system prompt
  - For each cycle (up to `max_tool_cycles`): call `_client.chat()` (non-streaming), parse for tool call
  - If tool call found: execute via `tool_registry.execute()`, log, append call + result to messages, continue
  - If no tool call: this is the final answer, break
- [x] 3.3 If max cycles exhausted, return a fallback message ("I'm sorry, I couldn't complete that request.")
- [x] 3.4 Commit only the final answer to `_history` via `_commit()` — tool turns are not stored in history
- [x] 3.5 Inject tool-calling instructions into the system prompt when `reply_agentic()` is used (explain `<tool_call>` JSON format, tool schemas, and that intermediate reasoning won't be spoken)

## 4. Tool handlers

- [x] 4.1 Implement `_tool_get_datetime(**args) -> dict`: returns `datetime.now().isoformat()`, timezone name, weekday
- [x] 4.2 Implement `_tool_get_state(key: str, actions_config=None) -> dict`: reads system vitals from `_read_system_vitals()` in actions.py, returns value for known keys (`temp_c`, `load`, `free_kb`, `uptime_s`)
- [x] 4.3 Implement `_tool_shell(command: str, whitelist: list[str]) -> dict`: validate against whitelist, execute via `asyncio.create_subprocess_shell` with `shlex.quote()`, return stdout/stderr (truncated to 1000 chars)
- [x] 4.4 Implement `_tool_mqtt_publish(topic: str, payload: str, mqtt_client, allowed_topics: list[str]) -> dict`: validate topic against allowed patterns, publish via `mqtt_client.publish()`
- [x] 4.5 Implement `_tool_set_volume(value: int) -> dict`: clamp to 0–100, convert to 0.0–1.0 float, call `set_output_volume()` + `save_volume_config()` from `audio_hw`

## 5. Register tools

- [x] 5.1 Create `build_default_tool_registry(mqtt_client=None, actions_config=None) -> ToolRegistry` function in `llm.py`
- [x] 5.2 Register all five tools with schemas (name, description, parameters with types/enum/constraints) and their handler functions
- [x] 5.3 Ensure `shell` schema lists the whitelist constraint, `set_volume` specifies value range 0–100, `mqtt_publish` requires topic + payload

## 6. Config changes

- [x] 6.1 Add fields to `LLMConfig`:
  - `tool_calling: bool = False`
  - `max_tool_cycles: int = 5`
  - `tool_calling_mode: str = "prompted_json"`
  - `shell_whitelist: list[str]` (with safe defaults)
  - `mqtt_allowed_topics: list[str] = field(default_factory=list)`
- [x] 6.2 Update `_parse_llm_config()` in `config.py` to parse new fields from YAML
- [x] 6.3 Add config validation: `tool_calling_mode` must be `"prompted_json"` (for now); `max_tool_cycles` must be >= 1

## 7. Wire into `llm_chat` action handler

- [x] 7.1 In `handle_llm_chat()` in `actions.py`, check `cfg.tool_calling`:
  - If `False`: call `engine.reply_streaming()` (unchanged)
  - If `True`: call `engine.reply_agentic()`, speak the returned text via TTS once
- [x] 7.2 Pass `mqtt_client` and `actions_config` down to `reply_agentic()` for use by tool handlers
- [x] 7.3 Build the tool registry via `build_default_tool_registry()` and pass it to `reply_agentic()`

## 8. Safety and logging

- [x] 8.1 Ensure shell tool rejects commands not matching any whitelist prefix (case-insensitive, prefix match)
- [x] 8.2 Ensure `set_volume` rejects non-integer values and clamps to 0–100
- [x] 8.3 Ensure `mqtt_publish` validates topic prefix against `mqtt_allowed_topics` (or allows all if list is empty)
- [x] 8.4 Add structured logging for every tool invocation: tool name, arguments, result, cycle number, timestamp
- [x] 8.5 Add `logger.warning` for rejected tool calls (whitelist violation, invalid args)

## 9. Tests

- [x] 9.1 Test `ToolRegistry` registration, schema listing, and `to_system_prompt_block()` output
- [x] 9.2 Test `_parse_tool_call()` with valid `<tool_call>...</tool_call>`, malformed JSON, multiple blocks, no block
- [x] 9.3 Test `_tool_get_datetime()` returns valid ISO datetime + timezone
- [x] 9.4 Test `_tool_set_volume()` clamps out-of-range values and rejects non-ints
- [x] 9.5 Test `_tool_shell()`: whitelisted command succeeds, non-whitelisted command is rejected
- [x] 9.6 Test `reply_agentic()` mock: LLM returns tool call → executes → continues → final answer returned
- [x] 9.7 Test max cycles: mock LLM returns tool call every time → fallback message returned after N cycles
- [x] 9.8 Test non-agentic path unchanged: `reply_streaming()` still streams and speaks sentence-by-sentence

## 10. Verification

- [x] 10.1 Run lint — no formatting or lint regressions (ruff passes)
- [x] 10.2 Run tests — 174 passed, 1 skipped (E2E smoke), same as baseline
- [x] 10.3 Verified: "what time is it?" → get_datetime tool called, returns e.g. "Wednesday, June 17, 2026, at 11:53 AM CEST"
- [x] 10.4 Verified: "what time is it and CPU temperature?" → get_datetime + get_state called, answer combines both
- [x] 10.5 Verified: "run rm -rf /" → shell rejects (whitelist), model explains it cannot run dangerous commands
