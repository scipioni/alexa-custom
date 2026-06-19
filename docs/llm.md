# Ollama Configuration

This document tracks local configuration changes made to the Ollama service on this host.

## Environment Variables Configuration

The following environment variables have been enabled to optimize performance and memory usage:

1. **`OLLAMA_FLASH_ATTENTION=1`**: Enables Flash Attention to speed up inference and reduce attention memory consumption.
2. **`OLLAMA_KV_CACHE_TYPE=q8_0`**: Enables 8-bit quantization for the Key-Value (KV) cache, significantly reducing memory usage per context token with negligible impact on accuracy.

---

## Configuration Details

These variables are defined in the Systemd drop-in configuration file for the Ollama service:

- **Configuration File Path:** `/etc/systemd/system/ollama.service.d/override.conf`
- **Backup File Path:** `/etc/systemd/system/ollama.service.d/override.conf.bak`

### Active Configuration

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_CONTEXT_LENGTH=32768"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
```

---

## Applying Changes

To apply or modify these settings manually in the future, run:

```bash
# 1. Reload the Systemd daemon configuration
sudo systemctl daemon-reload

# 2. Restart the Ollama service
sudo systemctl restart ollama
```

---

## Verification

### 1. Active Environment Verification
To verify that the environment variables are active in the running systemd service:

```bash
systemctl show --property=Environment ollama
```

**Expected Output:**
```text
Environment=HOME=/var/lib/ollama OLLAMA_MODELS=/var/lib/ollama OLLAMA_HOST=0.0.0.0:11434 OLLAMA_CONTEXT_LENGTH=32768 OLLAMA_FLASH_ATTENTION=1 
```

### 2. Service Logs Verification
To confirm that Ollama successfully recognized and loaded these settings at startup:

```bash
journalctl -u ollama -n 50 --no-pager
```

**Expected Log Confirmation:**
```text
level=INFO source=routes.go:1919 msg="server config" env="map[... OLLAMA_FLASH_ATTENTION:true ... OLLAMA_KV_CACHE_TYPE:q8_0 ...]"
```

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

## Agent Functionality

The alexa-custom daemon integrates Ollama as an optional voice AI backend. When configured, it provides two capabilities:

### 1. Free-form Conversation (fallback)

When a spoken command does not match any configured trigger, the transcript is automatically routed to the LLM if `fallback_on_no_match: true`. The conversation continues in a loop — the agent replies via TTS and listens for a follow-up — until the user says an exit phrase or stays silent for 10 seconds.

Say any exit phrase to end the session immediately and return to wake-word listening. The conversation history is preserved across exchanges within the same session and reset after `context_window_secs` of inactivity.

### 2. Explicit Chat (`llm_chat` action type)

A trigger can be configured to start a dedicated chat session directly:

```yaml
# in actions.yaml
triggers:
  - phrase: "parliamo"
    actions:
      - type: llm_chat
        # system_prompt: "..."  # optional per-trigger override
```

### 3. One-shot LLM narration (`say-with-llm` action type)

A trigger can send a prompt (and optionally the contents of a file) to the LLM and speak the streaming reply — without entering a listening loop. The exchange is recorded in the shared `ConversationEngine` history, so a subsequent `llm_chat` session can reference it.

```yaml
triggers:
  # Generative prompt
  - phrase: "dimmi qualcosa di interessante"
    actions:
      - type: say-with-llm
        prompt: "Dimmi una curiosità scientifica curiosa e poco nota"

  # File narration with instruction
  - phrase: "leggi le note"
    actions:
      - type: say-with-llm
        file: /home/scipio/notes.txt
        prompt: "Riassumi in modo conciso"
        max_chars: 2000    # default: 4000

  # Model override for this trigger only
  - phrase: "scrivi una poesia"
    actions:
      - type: say-with-llm
        prompt: "Scrivi una breve poesia sul tramonto"
        model: mistral:7b
```

**Parameters:**

| Parameter | Default | Description |
|---|---|---|
| `prompt` | `""` | Prompt sent to the LLM. Supports `$(shell)` substitution. |
| `file` | — | Path to a text file; content is prepended to `prompt`. |
| `max_chars` | `4000` | Max characters to read from `file`. |
| `lang` | `it-IT` | Language tag passed to TTS. |
| `model` | `llm.model` | Override the configured model for this action only. |

**Fallback behaviour:**
- If `llm:` is not configured in `config.yaml`, the text is spoken literally via TTS.
- If the Ollama endpoint is unreachable, the rendered `prompt` is spoken literally.

### 4. Command Learning (`llm_learn` action type)

A trigger can launch a voice wizard that teaches the agent a new command without editing config files:

```yaml
triggers:
  - phrase: "impara un comando"
    actions:
      - type: llm_learn
```

The wizard asks for a trigger phrase, what the command should do (free-form, parsed by the LLM), collects any required parameters, asks for confirmation, and writes the new trigger to `actions.yaml`. The file is hot-reloaded automatically.

---

## Configuration Reference (`config.yaml`)

```yaml
llm:
  backend: ollama
  host: http://192.168.1.10:11434   # remote Ollama URL (no local backend support)
  model: ssfdre38/gemma4-nano        # model name as shown by 'ollama list'
  context_turns: 10                 # conversation history depth (pairs of messages)
  context_window_secs: 60           # inactivity timeout before history is reset
  fallback_on_no_match: true        # route unmatched commands to LLM
  learn_commands: true              # enable llm_learn action type
  request_timeout: 10.0             # HTTP timeout for each Ollama request (seconds)
  system_prompt: null               # override the default voice-assistant system prompt
  exit_phrases:                     # words/phrases that end the conversation immediately
    - stop                          # omit this field to use the built-in defaults
    - basta
    - esci
    - fine
    - fermati
    - chiudi
    - exit
    - quit
    - annulla
    - cancella
```

**Notes:**
- `llm:` absent or `llm:` set to null disables the feature entirely.
- `exit_phrases` replaces the default list when set; list all phrases you want active.
- The conversation language follows the wake word group's `lang:` field (default `it-IT`).
- Ollama must be reachable at `host` before the first LLM call; if unreachable, the agent says *"agente remoto non raggiungibile"* and returns to wake-word listening.
