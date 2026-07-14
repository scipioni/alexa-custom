# Design — Async Wake Beep

## Context

Il beep di conferma è oggi sincrono nel thread di riconoscimento: `stt.py` chiama `play_wake_beep()` → `play_tone()` → `_play_array()`, che scrive un WAV temporaneo e lancia `subprocess.run(pw-play …)` **attendendone l'uscita** (più `post_playback_ms` di sleep). Misurato on-board: **1293 ms** tra il log del match e l'avvio del dispatch con `wake_tone: wake`, 3 ms con `wake_tone: none` (journal 2026-07-14, trigger "chiama assistenza").

Macchineria esistente in `_play_array` (`audio_ops.py`):
- `_audio_lock` — serializza *tutta* la riproduzione (beep, TTS, WAV): due playback non si sovrappongono mai.
- `_playback_active` (Event) — il gate che il loop di cattura usa per scartare i frame in-flight durante la riproduzione (soppressione eco); coperto per l'intera durata playback + `post_playback_ms`.
- Cleanup del WAV temporaneo nel `finally`.

Call-site del beep nel loop di riconoscimento (`stt.py`): wake beeps (661, 697, 717, 732), command beep pre-dispatch (822), follow-up tone (440).

## Goals / Non-Goals

**Goals:**
- Eliminare l'attesa sincrona del beep dal percorso match→dispatch (−1,29 s di latenza percepita).
- Preservare invariati: soppressione eco (gate `_playback_active`), serializzazione playback (`_audio_lock`), cleanup del WAV temporaneo, semantica `wake_tone: none`.
- Ripristinare `wake_tone: wake` in `conf/config.yaml`.

**Non-Goals:**
- Ridurre la latenza del decode sherpa-onnx (burst ~1,3 s intrinseco al modello kroko — appunti in memoria progetto, eventuale change separata).
- Cambiare la generazione dei toni o il formato di riproduzione (pw-play + WAV temporaneo restano — vincolo board, CLAUDE.md §6).
- Toccare il fast endpoint o `vad_silence_ms`.

## Decisions

**D1 — Thread, non spawn-senza-wait.** Nuovo helper `play_wake_beep_async(name)` in `audio_ops.py`: `threading.Thread(target=play_wake_beep, args=(name,), daemon=True).start()`. L'intero `_play_array` sincrono gira invariato nel thread di background, quindi lock, gate ed eliminazione del temp file continuano a funzionare senza modifiche. L'alternativa (Popen senza wait) richiederebbe di reinventare lifecycle del temp file e finestra del gate — scartata.

**D2 — Sovrapposizione beep/TTS: risolta dal lock esistente.** Il TTS della risposta acquisisce `_audio_lock` al momento del playback: se il beep sta ancora suonando, il TTS attende la fine del beep. Con Piper la sintesi della prima clausola (~1,9 s a freddo) supera comunque la durata del beep, quindi l'attesa aggiunta è ~0 nel caso tipico. Nessuna serializzazione aggiuntiva da implementare.

**D3 — Eco del beep: il gate resta il meccanismo primario.** `_playback_active` copre l'eco per l'intera durata del beep anche in async (il thread lo setta/pulisce come oggi). *Verificato in implementazione*: `flush_ms` vive solo nel percorso ask/reply (`capture_transcript`), non nel loop principale — lì l'eco è gestita da `_iter_gated_audio`, che scarta i chunk mentre `is_playback_active()` è set e a fine playback drena il pipe e resetta il backend. Con il beep async questa transizione viene effettivamente osservata dal loop (prima il loop era bloccato dentro la chiamata sincrona e il backlog — echo incluso — finiva nel recognizer al resume): la protezione eco risulta *migliorata*. Nessuna finestra di leak all'avvio: `_playback_active` viene settato prima che pw-play parta, e i chunk letti nel frattempo contengono solo audio ambiente.

**D4 — `wake_tone: none` invariato.** `play_wake_beep` già ritorna subito per `none`; l'helper async mantiene il check *prima* di creare il thread (nessun thread inutile).

**D5 — Tutti i call-site del loop migrano.** Wake beeps, command beep e follow-up tone usano l'helper async: il beneficio vale per ogni percorso (il wake beep sincrono ritarda l'apertura della wake window esattamente come il command beep ritardava il dispatch).

## Risks / Trade-offs

- **Eco del beep captato dal mic dopo il dispatch** → mitigato dal gate `_playback_active` (invariato). Verifica esplicita on-board nel piano task.
- **Beep multipli ravvicinati** (wake + comando in one-breath) → thread multipli si accodano su `_audio_lock`; durata beep ~centinaia di ms, coda bounded e innocua.
- **Il feedback acustico arriva mentre l'azione è già partita** → è l'obiettivo; per azioni con risposta vocale immediata il beep può accavallarsi alla *preparazione* della risposta ma mai all'audio (lock). UX da confermare all'ascolto.
- **Test di ordinamento tone→dispatch** → la spec pinnava "tone poi dispatch"; il delta spec la aggiorna a "tone avviato, dispatch concorrente". Eventuali test che asseriscono l'ordine stretto vanno aggiornati insieme.
- **Barge-in sopra il beep scartato** (scoperto in implementazione): con il beep sincrono, la voce pronunciata durante il beep si accumulava nel backlog del pipe e veniva riconosciuta al resume (insieme all'eco); con il gate attivo durante il beep async, i chunk vengono scartati per l'intera finestra (~0,8–1,3 s: il tono "wake" include 0,5 s di gap silenzioso in testa + pw-play spawn + `post_playback_ms`). Trade-off accettato: parlare sopra il beep non era comunque un percorso affidabile (l'eco inquinava il transcript). Se servisse barge-in reale, è una change separata (es. echo cancellation o gate selettivo).
