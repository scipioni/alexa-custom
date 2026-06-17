## 1. Extend tool metadata in llm.py

- [ ] 1.1 Add optional params and JSON Schema descriptions to `_ACTION_PARAMS` and `_WIZARD_ALLOWED_TYPES`
- [ ] 1.2 Add Italian tool descriptions to `_ACTION_LABELS` for every action type
- [ ] 1.3 Add shell allowlist field to `LLMConfig` dataclass

## 2. Implement AgenticLoopEngine

- [ ] 2.1 Create `AgenticLoopEngine` class in `llm.py` with tool definition generation from metadata
- [ ] 2.2 Implement `generate_tool_definitions()` that produces OpenAI-compatible JSON Schema
- [ ] 2.3 Implement `run()` method: send message with tools, parse response, dispatch tool_calls, re-feed results
- [ ] 2.4 Implement max-iterations guard (cap at 5 tool calls per user turn)
- [ ] 2.5 Implement fallback to non-agentic mode when model returns text without tool_calls

## 3. Implement shell allowlist

- [ ] 3.1 Add `fnmatch`-based allowlist check in the agentic dispatch path
- [ ] 3.2 Default allowlist with safe read-only commands
- [ ] 3.3 Wire `LLMConfig.shell_allowed_commands` into the check

## 4. Wire agentic wrapper in actions.py

- [ ] 4.1 Create `handle_llm_chat_agentic` action handler in `actions.py`
- [ ] 4.2 Instantiate `AgenticLoopEngine` and call its `run()` method
- [ ] 4.3 Handle the final response text: stream to TTS via `say_fn`
- [ ] 4.4 Register `llm_chat_agentic` in the `ActionRegistry` alongside the existing `llm_chat`
- [ ] 4.5 Register both `llm_chat` and `llm_chat_agentic` as aliases for the same handler (or keep separate)

## 5. Configure CrofAI

- [ ] 5.1 Add CrofAI API key and base URL to `conf/secrets.yaml`
- [ ] 5.2 Set `deepseek-v4-flash` as default model in `conf/config.yaml`
- [ ] 5.3 Set `backend: openai` in LLM config section to use CrofAI

## 6. Tests

- [ ] 6.1 Write unit tests for `AgenticLoopEngine.generate_tool_definitions()`
- [ ] 6.2 Write unit tests for tool dispatch and result re-feed
- [ ] 6.3 Write unit tests for shell allowlist validation
- [ ] 6.4 Write unit tests for max-iterations guard
