## Why

The assistant only responds to pre-defined trigger phrases. Any utterance that doesn't match a known command is silently dropped. Adding an Ollama-backed conversation layer turns the device into a general-purpose voice AI that can answer free-form questions and teach itself new commands without the user ever editing a config file.

## What Changes

- **New `llm.py` module**: `OllamaClient`, `ConversationEngine`, `LearnWizard`, `ActionsFileStore`
- **New `actions.yaml`** file referenced by `config.yaml` via `actions_file:` key — holds all trigger/action definitions (global + per-wake-word), writable by the agent
- **`config.yaml` split**: triggers and wake-word-specific trigger lists move out to `actions.yaml`; credentials, devices, STT/TTS, LLM settings, `on_startup` stay in `config.yaml`
- **`config.py`**: new `LLMConfig` dataclass; `WakeWordGroup` gains a `lang` field (default `it-IT`); config loader gains `actions_file` support
- **`config_manager.py`**: watches both `config.yaml` and `actions.yaml`, merges `wake_triggers` into the matching `WakeWordGroup.triggers` at load time
- **`actions.py`**: two new action types — `llm_chat` (explicit free-form conversation) and `llm_learn` (command wizard)
- **`stt.py`**: `nomatch` branches check for LLM fallback before calling `_play_timeout()`
- **`config.yaml.example`**: add `llm:` block and `actions_file:` reference; extract example triggers into `actions.yaml.example`
- If Ollama is not configured, the feature is fully disabled — zero behaviour change
- If Ollama is unreachable at runtime, the assistant speaks "agente remoto non raggiungibile"

## Capabilities

### New Capabilities

- `llm-conversation`: Free-form voice chat via remote Ollama. Routes unmatched commands to a rolling-history `ConversationEngine`. Language follows the active wake word group's `lang` field (default `it-IT`). Conversation context is time-windowed (configurable, default 60 s).
- `llm-command-learning`: `LearnWizard` — multi-turn voice wizard that elicits a trigger phrase and one or more chained actions (allowed types: `say`, `tone`, `shell`, `mqtt_publish`, `telegram`, `livekit_join`), confirms with the user, then appends the new trigger to `actions.yaml`. Hot-reload makes it live within 4 s.
- `actions-file`: `actions.yaml` as the dedicated, agent-writable source of truth for all trigger/action definitions. Schema: top-level `triggers:` list (global fallback) and `wake_triggers:` map (per-wake-word overrides). Referenced from `config.yaml` via `actions_file:`.

### Modified Capabilities

- `action-dispatch`: trigger resolution now merges from `actions.yaml` in addition to inline config; no change to the dispatch contract itself
- `yaml-config`: `config.yaml` loses the top-level `triggers:` key and per-wake-word `triggers:` sub-keys (moved to `actions.yaml`); gains `actions_file:` and `llm:` top-level keys

## Impact

- **New dependency**: `httpx` (async HTTP for Ollama API) — already available in most Python 3.13 environments; add to `pyproject.toml`
- **New optional dependency**: `ruamel.yaml` for round-trip YAML writes to `actions.yaml`
- **`config.yaml` migration**: existing configs with inline `triggers:` continue to work (backward-compatible fallback in the loader); `actions_file:` is optional
- **No audio path changes** — the LLM path reuses existing `listen_fn` and TTS (`say` action) infrastructure
- **Board impact**: Ollama is remote-only; no local inference load on the Snapdragon 801
