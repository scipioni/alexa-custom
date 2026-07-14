## 1. Register the action handler

- [x] 1.1 Add `handle_say_with_llm` async function in `actions.py` decorated with `@registry.register("say-with-llm")`
- [x] 1.2 Import `_split_sentences`, `get_engine as get_llm_engine`, and `_UNREACHABLE` from `alexa_custom.llm` inside the handler (lazy import, matching existing pattern)

## 2. Implement parameter handling

- [x] 2.1 Read and `_render_text()` the `prompt` param (default `""`)
- [x] 2.2 Read `file`, `lang` (default `"it-IT"`), `max_chars` (default `4000`), and `model` params
- [x] 2.3 If `file` is set, read up to `max_chars` characters; log a warning on `OSError` and continue without file content
- [x] 2.4 Build `user_text` by joining non-empty file content and rendered prompt with `"\n\n"`; return early if empty

## 3. Implement LLM path

- [x] 3.1 If `actions_config` is `None` or `actions_config.llm` is `None`, fall back to literal TTS (speak `user_text`) and return
- [x] 3.2 Obtain shared engine via `get_llm_engine(cfg, lang)` — use `model` override when set (pass as kwarg or construct a modified config copy)
- [x] 3.3 Define `say_fn` coroutine that calls `asyncio.to_thread(get_tts().say, text, lang)`
- [x] 3.4 Call `await engine.reply_streaming(user_text, say_fn)` and capture the return value
- [x] 3.5 If return value is `_UNREACHABLE`, speak the rendered `prompt` (not file content) literally via TTS as fallback

## 4. Model override wiring

- [x] 4.1 Check how `ConversationEngine` uses `cfg.model` — confirm whether passing a modified `LLMConfig` to `get_llm_engine` produces a separate cache key (it should, since the cache key includes `model`)
- [x] 4.2 If `model` param is set, construct a shallow-copy of `cfg` with `model` replaced so the override is scoped to this call's engine instance

## 5. Tests

- [x] 5.1 Add `tests/test_say_with_llm.py` with a test that patches `get_llm_engine` and `get_tts` and verifies the handler calls `reply_streaming` with the correct `user_text`
- [x] 5.2 Test file injection: mock `Path.read_text`, verify file content is prepended to prompt
- [x] 5.3 Test `max_chars` truncation: file content longer than limit is sliced before being passed
- [x] 5.4 Test missing file: `OSError` is caught, action proceeds with prompt-only
- [x] 5.5 Test LLM-not-configured fallback: `actions_config.llm is None` → `get_tts().say` called with `user_text`
- [x] 5.6 Test `_UNREACHABLE` fallback: `reply_streaming` returns sentinel → `get_tts().say` called with rendered prompt only
- [x] 5.7 Test template rendering: `{date}` in prompt is expanded before being sent to LLM

## 6. Documentation

- [x] 6.1 Add `say-with-llm` entry to `conf/config.example.yaml` (or equivalent docs) with all params and inline comments
- [x] 6.2 Add recommended Ollama models table to `docs/` or README (`gemma2:2b`, `qwen2.5:3b`, `llama3.2:3b`, `mistral:7b` with size/quality notes)
