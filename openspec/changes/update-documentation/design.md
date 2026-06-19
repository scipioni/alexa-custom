## Context

La documentazione attuale riflette lo stato del codice prima di 8+ cambiamenti significativi: refactoring STT da due stadi a modello singolo, introduzione backend GStreamer con webrtcdsp, profili di cattura audio con switching vocale, AudioWatcher per il routing, PCM restore dopo pulsectl, web config panel, display feedback, LLM wizard, sleeping mode, follow-up conversation, nuovi comandi CLI.

Tutti i doc .md e README.md necessitano di aggiornamento. I conf.example/*.yaml sono già allineati e non richiedono modifiche.

## Goals / Non-Goals

**Goals:**
- Ogni documento .md deve riflettere accuratamente lo stato corrente del codice
- Tutte le chiavi di configurazione devono essere documentate con valori di default evidenziati
- Tutti i comandi CLI (alexa-*, serena-*) e task devono essere elencati
- Tutte le action type devono essere documentate con parametri
- I valori di default devono essere coerenti con config.py

**Non-Goals:**
- Modificare codice sorgente
- Modificare i file conf.example/* (già aggiornati)
- Aggiungere nuova documentazione per feature non ancora implementate
- Tradurre la documentazione

## Decisions

1. **docs/stt-simple.md come sorgente unica**: stt-simple.md diventa il riferimento completo del pipeline STT. stt.md diventa una panoramica concisa che rimanda a stt-simple.md. Si evita la duplicazione che ha causato il divergence attuale.

2. **Valori di default in grassetto**: ogni chiave di configurazione viene presentata con il valore di default in grassetto (es. `vad_silence_ms: 900`), rendendo immediatamente visibile cosa cambia omettendo la chiave.

3. **Tabella action types completa**: ogni action type viene documentata con tipo, parametri obbligatori/opzionali, descrizione — derivata dal codice `actions.py` (registry.register).

4. **Raggruppamento logico**: CLI raggruppati in "daemon", "audio", "STT", "utility"; task raggruppati in "sviluppo", "audio", "display", "release". Facilita la consultazione.

5. **Nessun symlink**: docs/stt.md e docs/stt-simple.md rimangono file separati (non symlink) per chiarezza in git e navigazione.

## Risks / Trade-offs

- **[Rischio divergenza futura]** → Mitigazione: aggiungere un commento in AGENTS.md che impone di aggiornare la documentazione parallelamente al codice.
- **[Dimensione dei file]** → docs/configuration.md e docs/stt-simple.md diventano molto lunghi. Trade-off accettabile: meglio un file lungo e completo che 5 file corti e obsoleti.
- **[Valori di default ridondanti]** → Se config.py cambia un default e la doc non viene aggiornata, si genera divergenza. Trade-off: necessario sync manuale, ma il valore aggiunto per l'utente supera il costo.
