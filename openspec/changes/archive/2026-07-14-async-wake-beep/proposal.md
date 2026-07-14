# Async Wake Beep

## Why

Il beep di conferma (`play_wake_beep`) viene riprodotto in modo **sincrono** nel thread di riconoscimento prima di lanciare il dispatch dell'azione: su questa board un tono = WAV temporaneo + spawn di `pw-play` + attesa della fine riproduzione, misurati **1,29 s** (journal 2026-07-14: gap match→dispatch 1293 ms con beep, 3 ms senza). È la singola fetta di latenza percepita più grande e più facilmente eliminabile della pipeline comando→risposta.

## What Changes

- Il beep di wake/comando/follow-up parte **in parallelo** al dispatch dell'azione invece di bloccarlo: il thread di riconoscimento non attende più la fine della riproduzione del tono.
- Tutti i call-site di `play_wake_beep` nel loop di riconoscimento (`stt.py`: wake beeps, command beep pre-dispatch, follow-up tone) usano il percorso non bloccante; il comportamento con `wake_tone: none` resta invariato (nessun processo lanciato).
- `conf/config.yaml`: ripristino di `wake_tone: wake` (portato temporaneamente a `none` il 2026-07-14 come esperimento diagnostico).
- Verifica esplicita dei meccanismi che oggi si appoggiano implicitamente alla durata sincrona del beep:
  - `flush_ms` (scarto dell'eco del beep dopo il wake): l'audio del beep captato dal microfono ora arriva *durante/dopo* l'inizio del dispatch — il flush deve continuare ad assorbirlo.
  - Sovrapposizione beep/TTS: con il dispatch anticipato, il TTS della risposta (es. `ask`) può partire mentre il beep sta ancora suonando. Decisione di design richiesta: sovrapposizione accettabile vs serializzazione lato playback.

## Capabilities

### New Capabilities

(nessuna)

### Modified Capabilities

- `single-model-stt`: il requisito "Endpoint-gated matching with confirmation tone" e il loop "transcribe→match→gate→tone→dispatch" cambiano semantica: il tono viene *avviato* alla conferma del match ma non ritarda più il dispatch (tone e dispatch concorrenti invece che sequenziali).

## Impact

- `alexa_custom/stt.py` — call-site del beep nel loop di riconoscimento (wake, comando pre-dispatch, follow-up tone) e interazione con `flush_ms`.
- `alexa_custom/audio_ops.py` — `play_wake_beep`/`play_tone`: variante non bloccante (spawn di `pw-play` senza wait, gestione del file WAV temporaneo che non può essere cancellato prima della fine riproduzione).
- `conf/config.yaml` — ripristino `wake_tone: wake`.
- Test: `tests/` per il percorso tone→dispatch (pipeline-level, ScriptedBackend) — il gate "nessun tono prima dell'endpoint" resta valido e pinnato.
- Latenza attesa: −1,29 s su ogni comando con beep attivo; nessun impatto quando `wake_tone: none`.
