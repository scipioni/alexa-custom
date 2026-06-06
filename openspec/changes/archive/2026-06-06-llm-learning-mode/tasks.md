## 1. Dependencies and config schema

- [x] 1.1 Add `httpx` and `ruamel.yaml` to `pyproject.toml` dependencies
- [x] 1.2 Add `LLMConfig` dataclass to `config.py` with all fields and defaults
- [x] 1.3 Add `lang: str = "it-IT"` field to `WakeWordGroup` dataclass
- [x] 1.4 Add `actions_file: str | None` and `llm: LLMConfig | None` to the main config dataclass
- [x] 1.5 Add `actions_file` and `llm` parsing to `_parse_config()` in `config.py`; reject `llm.backend != "ollama"` with `ConfigError`
- [x] 1.6 Add `lang` parsing to `_parse_wake_word_groups()` in `config.py`

## 2. `actions.yaml` support in config loader

- [x] 2.1 Define `ActionsData` dataclass (or TypedDict) with `triggers` and `wake_triggers` fields
- [x] 2.2 Write `_parse_actions_file(path) -> ActionsData` in `config.py` using the existing `_parse_triggers()` helper
- [x] 2.3 In `_parse_config()`, after parsing inline triggers, load and merge `actions.yaml` when `actions_file` is set: append global triggers, append per-group triggers for matching `WakeWordGroup` entries; log debug for unknown wake word keys
- [x] 2.4 Update `config_manager.py` hot-reload watcher to also stat `actions.yaml` and trigger a reload when it changes
- [x] 2.5 Add backward-compat: if `actions_file` is absent but `actions.yaml` exists alongside `config.yaml`, log a one-time info suggesting `actions_file:` when `learn_commands` is enabled

## 3. `ActionsFileStore` (write side)

- [x] 3.1 Create `alexa_custom/llm.py` with `ActionsFileStore` class
- [x] 3.2 Implement `ActionsFileStore.load(path) -> ActionsData` using `ruamel.yaml` round-trip loader
- [x] 3.3 Implement `ActionsFileStore.save(path, data: ActionsData)` with write-to-temp-then-rename atomicity
- [x] 3.4 Implement `ActionsFileStore.append_trigger(path, trigger, wake_word=None)`: load, insert `# --- learned commands ---` separator on first learned entry, append trigger, save
- [x] 3.5 Write unit tests for load/save round-trip and append_trigger (including separator insertion)

## 4. `OllamaClient`

- [x] 4.1 Implement `OllamaClient` in `llm.py`: async `chat(messages, model, timeout) -> str` using `httpx.AsyncClient` POST to `/api/chat` (non-streaming, `stream: false`)
- [x] 4.2 Define `OllamaUnreachable` exception; raise it on `httpx.ConnectError`, `httpx.TimeoutException`, and non-2xx responses
- [x] 4.3 Write unit tests for `OllamaClient` with `httpx` mocking (success, unreachable, timeout)

## 5. `ConversationEngine`

- [x] 5.1 Implement `ConversationEngine.__init__(config: LLMConfig, lang: str)` with rolling history list and `_last_ts` monotonic timestamp
- [x] 5.2 Implement `ConversationEngine.reply(user_text: str) -> str`: reset history if expired, append user message, call `OllamaClient.chat`, append assistant reply, return text; on `OllamaUnreachable` return sentinel `"__UNREACHABLE__"`
- [x] 5.3 Build system prompt in `ConversationEngine`: plain prose, TTS-appropriate, language-aware; include optional `config.system_prompt` override
- [x] 5.4 Write unit tests for history rolling, time-window reset, and unreachable sentinel

## 6. `LearnWizard`

- [x] 6.1 Implement `LearnWizard.__init__(config: LLMConfig, lang: str, actions_file_path: str)` 
- [x] 6.2 Implement wizard step 1: speak "Che frase vuoi usare?" and listen for trigger phrase
- [x] 6.3 Implement wizard step 2: speak "Cosa deve fare?" and send free-form reply to Ollama with an action-extraction system prompt; parse result into list of `{type, ...params}` dicts using only the allowed action types
- [x] 6.4 Implement wizard step 3: loop over identified actions, speak param questions and listen for each required param; reject disallowed action types with voice feedback
- [x] 6.5 Implement wizard step 4: speak full summary and ask "Confermi?"; listen for yes/no/annulla; on timeout treat as cancel
- [x] 6.6 On confirmation, call `ActionsFileStore.append_trigger()` with the assembled `Trigger`; speak "Comando salvato" or "Operazione annullata"
- [x] 6.7 Write integration test: mock `listen_fn`, `say_fn`, and `OllamaClient`; assert correct `Trigger` is produced and written

## 7. New action types in `actions.py`

- [x] 7.1 Register `llm_chat` action handler: enter `ConversationEngine` multi-turn loop (listen → reply via TTS → listen, up to `context_turns` exchanges); use per-action `system_prompt` override if present; play `info` tone before first LLM call
- [x] 7.2 Register `llm_learn` action handler: instantiate `LearnWizard` and call `run(listen_fn, say_fn, wake_word)`
- [x] 7.3 Both handlers: if `config.llm is None`, log warning and return immediately

## 8. LLM fallback in `stt.py`

- [x] 8.1 Extract shared `_llm_fallback(transcript, config, listen_fn, say_fn, dispatch_loop)` helper
- [x] 8.2 In `_run_two_stage`: replace `_play_timeout()` on nomatch with `_llm_fallback(...)` when `config.llm` and `config.llm.fallback_on_no_match`; keep `_play_timeout()` as the else branch
- [x] 8.3 In `_run_single_stage`: same substitution at both nomatch sites (lines ~821 and ~829)
- [x] 8.4 In `_llm_fallback`: play `info` tone, call `ConversationEngine.reply()`, if sentinel speak "agente remoto non raggiungibile", else speak reply via TTS; loop once for follow-up (listen, reply) before returning to wake-word loop

## 9. Config example files

- [x] 9.1 Add `actions.yaml.example` with the full schema (global `triggers:` + `wake_triggers:` map) and clear comments
- [x] 9.2 Update `config.yaml.example`: add `actions_file: actions.yaml` key; add `llm:` block with all fields commented/documented; move example `triggers:` entries to a note pointing at `actions.yaml.example`; add `lang:` field to wake word group examples

## 10. Tests and validation

- [x] 10.1 Add `config.py` tests: `actions_file` merge (global + per-wake-word), unknown wake word key ignored, `LLMConfig` parsing, `lang` field default and override, invalid backend raises `ConfigError`
- [x] 10.2 Add `config_manager.py` test: modifying `actions.yaml` triggers a hot-reload callback
- [x] 10.3 End-to-end smoke test: start system with `llm:` configured, speak an unmatched command, assert `info` tone plays and `ConversationEngine.reply` is called (mock Ollama)
