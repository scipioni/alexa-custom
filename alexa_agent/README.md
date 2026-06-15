# alexa_agent — Agente Conversazionale su LiveKit

Pacchetto che implementa un agente AI conversazionale attivabile vocalmente. L'agente si connette a una stanza LiveKit, ascolta l'audio dei partecipanti, lo trascrive con Vosk, lo elabora con un LLM (Groq di default) e risponde via Piper TTS.

## Struttura

```
alexa_agent/
├── agent.py          ← Script principale: loop Vosk → LLM → Piper su LiveKit
├── session.py        ← Orchestrazione: creazione stanza, token JWT, avvio agente
├── actions.py        ← Copia di alexa_custom/actions.py (modificato)
├── config.py         ← Copia di alexa_custom/config.py (modificato: groq_api_key)
├── web.py            ← Copia di alexa_custom/web.py (modificato: WEB_PORT export)
├── llm.py            ← Copia di alexa_custom/llm.py (modificato: extra_body)
├── __init__.py
├── docs/             ← Artifact OpenSpec della change agentic-room
│   ├── proposal.md
│   ├── design.md
│   ├── tasks.md
│   └── specs/agent-session/spec.md
└── README.md
```

## Cosa è stato cambiato rispetto a `develop`

### Nuovi file

| File | Dettaglio |
|---|---|
| `agent.py` | Script principale (~450 righe). Si connette a stanza LiveKit, stream audio → Vosk (16kHz) → LLM (Groq Llama 3.1 via `OpenAIClient`) → Piper TTS → LiveKit AudioSource. VAD con timeout 600ms, streaming LLM con sentence splitting, cooldown post-TTS 1s, RMS gate 0.001. Tutti i parametri in `AgentConfig` dataclass. |
| `session.py` | 3 funzioni estratte da `alexa_custom/actions.py`. Orchestrazione stanza LiveKit, token JWT, subprocess agent. |
| `docs/` | 4 artifact OpenSpec della change. |

### File modificati (copie in `alexa_agent/`)

| File | Modifica |
|---|---|
| `actions.py` | Rimossa `_create_agent_room`, `_generate_agent_tokens`, `handle_agent_session`. Aggiunto `registry.register("agent_session")` da `alexa_agent.session`. |
| `config.py` | Aggiunto campo `groq_api_key: str \| None = None` in `SecretsConfig` + env var. |
| `web.py` | Aggiunto `os.environ["WEB_PORT"] = str(port)`. |
| `llm.py` | `OpenAIClient.chat_stream()` ora accetta `extra_body: dict \| None` per parametri aggiuntivi (temperature, max_tokens). |

### Invariato

| File | Note |
|---|---|
| `conf/actions/system.yaml` | Trigger `"aiuto agente"` → `agent_session` già presente su develop. |

## Flusso di esecuzione

```
Wake word "ascolta assistente" + comando "aiuto agente"
         │
         ▼
alexa_custom/actions.py
  registry["agent_session"] → alexa_agent.session.handle_agent_session()
         │
         ├── Crea stanza LiveKit (empty_timeout=300s)
         ├── Genera JWT: user (microfono) + agent (ai-agent)
         ├── subprocess.Popen(alexa_agent/agent.py --room X --token Y --url Z)
         └── Apre browser → meet.livekit.io/custom/ con user_token
                  │
                  ▼
         alexa_agent/agent.py (processo separato)
           │
           ├── Connessione a stanza LiveKit
           ├── Beep + "Ciao, sono il tuo assistente..."
           ├── Loop: AudioStream → Vosk (16kHz)
           │              ├── VAD (600ms silenzio → finalizza)
           │              ├── RMS gate (0.001)
           │              └── Cooldown post-TTS (1s)
           ├── Streaming LLM → sentence splitter → Piper (frase per frase)
           └── Disconnessione: solo quando il partecipante esce
```

## Configurazione

Tutti i parametri in `AgentConfig` (inizio di `agent.py`):

| Parametro | Default | Cosa fa |
|---|---|---|
| `llm_model` | `llama-3.1-8b-instant` | Modello LLM |
| `llm_base_url` | `https://api.groq.com/openai` | Endpoint LLM |
| `temperature` | `0.3` | Creatività del LLM |
| `max_tokens` | `80` | Max token per risposta |
| `system_prompt` | "...massimo una frase..." | Prompt di sistema |
| `rms_threshold` | `0.001` | Soglia rumore audio |
| `vad_silence_ms` | `600` | Silenzio prima di finalizzare |
| `tts_cooldown_ms` | `1000` | Cooldown post-TTS |

## Dipendenze

- `livekit` / `livekit-api` — stanza, token, stream audio
- `vosk` — speech-to-text locale (modello `models/it`)
- `alexa_custom.llm.OpenAIClient` — client LLM (Groq, Ollama, vLLM, ecc.)
- `piper-tts` — text-to-speech locale (voce `it_IT-paola-medium`)
