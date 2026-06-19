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

### 3. One-shot LLM narration (`say-with-llm`)

A trigger sends a prompt (and optionally a file) to the LLM and speaks the streaming reply — without entering a listening loop. The exchange is recorded in the shared `ConversationEngine` history, so a subsequent `llm_chat` session can reference it.

```yaml
triggers:
  # Generative prompt
  - commands: ["dimmi qualcosa di interessante"]
    actions:
      - type: say-with-llm
        prompt: "Dimmi una curiosità scientifica poco nota"

  # File narration with instruction
  - commands: ["leggi le note"]
    actions:
      - type: say-with-llm
        file: /home/scipio/notes.txt
        prompt: "Riassumi in modo conciso"
        max_chars: 2000    # default: 4000

  # Model override for this trigger only
  - commands: ["scrivi una poesia"]
    actions:
      - type: say-with-llm
        prompt: "Scrivi una breve poesia sul tramonto"
        model: mistral:7b
```

| Parameter | Default | Description |
|---|---|---|
| `prompt` | `""` | Prompt sent to the LLM. Supports `$(shell)` substitution. |
| `file` | — | Path to a text file; content is prepended to `prompt`. |
| `max_chars` | `4000` | Max characters to read from `file`. |
| `lang` | `it-IT` | Language tag passed to TTS. |
| `model` | `llm.model` | Override the configured model for this action only. |

Falls back to literal TTS if `llm:` is not configured or the endpoint is unreachable.

### 4. Command Learning (`llm_learn`)

Voice wizard that creates new triggers without editing config files:

```yaml
triggers:
  - commands: ["impara nuovo comando"]
    actions:
      - type: llm_learn
```

The wizard asks for a trigger phrase, what the command should do, collects parameters, confirms, and writes to `actions.learn_file` (default: `conf/actions/learned.yaml`). Hot-reloaded automatically.

---

## Recommended Models

All models run on the Ollama **server** (not the Arduino Uno Q board). Choose based on available server RAM and your latency/quality trade-off:

| Model | Size (Q4) | Italian | Notes |
|---|---|---|---|
| `ssfdre38/gemma4-nano` | ~0.5 GB | good | Default — fastest, lowest RAM, ideal for quick one-shot prompts |
| `gemma2:2b` | ~1.6 GB | excellent | Best quality/speed for Italian at 2 B parameters |
| `qwen2.5:3b` | ~2.0 GB | very good | Strong multilingual instruction-following |
| `llama3.2:3b` | ~2.0 GB | good | Meta's current small model, solid general purpose |
| `phi4-mini` | ~2.5 GB | good | Microsoft; very precise instruction-following |
| `mistral:7b` | ~4.1 GB | excellent | Best output quality; needs ≥ 8 GB server RAM |
| `gemma3:4b` | ~3.0 GB | very good | Google's updated line; good Italian prose |

**Tips for voice use:**
- Smaller models start replying faster — important for perceived latency on the first TTS sentence.
- Any model benefits from the system prompt instructing it to avoid markdown (already done by default).
- `ollama pull <model>` on the server to download; then set `model:` in `config.yaml`.

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
