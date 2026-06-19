# LLM Integration

The daemon integrates with any OpenAI-compatible LLM endpoint (Ollama, OpenAI API, LM Studio, vLLM). Two backends are supported: `ollama` and `openai`.

---

## Backends

### Ollama (local)

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Recommended: `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_CONTEXT_LENGTH=32768`.

### OpenAI API (remote)

Set `llm.backend: openai` and provide `llm_api_key` in `conf/secrets.yaml`. Works with any OpenAI-compatible endpoint — just set `llm_host` to the full base URL (e.g. `https://api.openai.com/v1`).

---

## Features

### 1. Fallback Conversation

When `llm.fallback_on_no_match: true`, unmatched commands are routed to the LLM. The system replies via TTS and listens for follow-up. Exit phrases end the session:

```yaml
llm:
  fallback_on_no_match: true
```

Default exit phrases: `stop`, `esci`, `basta`, `fine`, `fermati`, `chiudi`, `exit`, `quit`, `annulla`, `cancella`. Override with `llm.exit_phrases:`.

### 2. Explicit Chat (`llm_chat`)

```yaml
triggers:
  - commands: ["parliamo"]
    actions:
      - type: llm_chat
        # system_prompt: "..."  # per-trigger override
```

Multi-turn conversation via listen → LLM reply → speak loop. History resets after `context_window_secs` of inactivity. Max `context_turns` exchange pairs.

### 3. Command Learning (`llm_learn`)

Voice wizard that creates new triggers without editing config files:

```yaml
triggers:
  - commands: ["impara nuovo comando"]
    actions:
      - type: llm_learn
```

The wizard asks for a trigger phrase, what the command should do, collects parameters, confirms, and writes to `actions.learn_file` (default: `conf/actions/learned.yaml`). Hot-reloaded automatically.

---

## Configuration

```yaml
llm:
  backend: ollama                   # ollama | openai
  model: ssfdre38/gemma4-nano       # model name
  context_turns: 10                 # conversation history depth
  context_window_secs: 60           # timeout before history reset
  fallback_on_no_match: false       # route unmatched commands to LLM
  learn_commands: true              # enable llm_learn action type
  request_timeout: 60.0             # HTTP timeout
  system_prompt: null               # optional system prompt override
  exit_phrases:                     # override default exit phrases
    - stop
    - esci
    - basta
```

`llm_host` (required) and `llm_api_key` (optional) go in `conf/secrets.yaml`:

```yaml
llm_host: http://127.0.0.1:11434
# llm_api_key: sk-...
```

> **Note**: If the LLM endpoint is unreachable, the agent says *"agente remoto non raggiungibile"* and returns to wake-word listening.
