# alexa_agent — Agente Conversazionale su LiveKit

Pacchetto che implementa un agente AI conversazionale attivabile vocalmente. L'agente si connette a una stanza LiveKit, ascolta l'audio dei partecipanti, lo trascrive con Vosk, lo elabora con Groq (Llama 3.1) e risponde via Piper TTS.

## Struttura

```
alexa_agent/
├── agent.py          ← Script principale: loop Vosk → Groq → Piper su LiveKit
├── session.py        ← Orchestrazione: creazione stanza, token JWT, avvio agente
├── config.py         ← Copia di alexa_custom/config.py (modificato: groq_api_key)
├── web.py            ← Copia di alexa_custom/web.py (modificato: WEB_PORT export)
├── __init__.py
├── docs/             ← Artifact OpenSpec della change agentic-room
│   ├── proposal.md
│   ├── design.md
│   ├── tasks.md
│   └── specs/agent-session/spec.md
└── README.md
```

## Cosa è stato cambiato rispetto a `develop`

| File | Tipo modifica | Dettaglio |
|---|---|---|
| `agent.py` | **Nuovo** | 262 righe. Main loop: si connette a stanza LiveKit, apre stream audio, riconosce speech con Vosk KaldiRecognizer, invia a Groq LLM (`llama-3.1-8b-instant`, `max_tokens=200`), sintetizza risposta con Piper TTS e la pubblica come track audio LiveKit. Play beep di benvenuto all'avvio. Timeout sessione 180s. |
| `session.py` | **Nuovo** | 3 funzioni estratte da `alexa_custom/actions.py`:<br>`_create_agent_room(name)` — crea stanza LiveKit via API con `empty_timeout=300s`<br>`_generate_agent_tokens(name)` — genera JWT utente (microfono) e agente<br>`handle_agent_session(action)` — orchestratore: stanza → token → subprocess `agent.py` → browser tab |
| `alexa_custom/actions.py` | **Modificato** | Rimosse le 3 funzioni sopra. Aggiunto `from alexa_agent import session` con registrazione su `registry.register("agent_session")`. |
| `alexa_custom/config.py` | **Modificato** | Aggiunto campo `groq_api_key: str \| None = None` in `SecretsConfig`. Iniezione in `os.environ["GROQ_API_KEY"]` in `load_secrets()`. |
| `alexa_custom/web.py` | **Modificato** | Aggiunto `os.environ["WEB_PORT"] = str(port)` nel costruttore `WebServer.__init__()`. |
| `conf/actions/system.yaml` | **Inalterato** | Il trigger `"aiuto agente"` → `agent_session` era già presente su `develop`. |

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
           ├── Loop: AudioStream → Vosk (16kHz) → Groq → Piper → LiveKit AudioSource
           └── Disconnessione: partecipante esce o timeout 180s
```

## Dipendenze

- `livekit` / `livekit-api` — stanza, token, stream audio
- `vosk` — speech-to-text locale (modello `models/it`)
- `openai` — client Groq (`llama-3.1-8b-instant`)
- `piper-tts` — text-to-speech locale (voce `it_IT-paola-medium`)

## Problema noto

L'agente "parla troppo" dopo la risposta desiderata. Cause:

1. **LLM verboso** — `max_tokens=200` permette ~150 parole, molto più del necessario
2. **Nessun cooldown post-TTS** — il loop rimane in ascolto e può captare l'eco del browser, causando risposte a catena

Vedi `docs/tasks.md` per le correzioni pianificate.
