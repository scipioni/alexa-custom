# Tasks — Async Wake Beep

## 1. Helper non bloccante

- [x] 1.1 Aggiungere `play_wake_beep_async(name)` in `alexa_custom/audio_ops.py`: check `name == "none"` prima di creare il thread, poi `threading.Thread(target=play_wake_beep, args=(name,), daemon=True).start()`; ri-esportare da `alexa_custom/audio.py` come già fatto per `play_wake_beep`
- [x] 1.2 Unit test dell'helper: con `wake_tone: none` nessun thread/playback avviato; con tono valido la chiamata ritorna subito (< qualche ms) e il playback avviene (mock di `_play_array`/`play_tone`)

## 2. Migrazione call-site nel loop di riconoscimento

- [x] 2.1 Sostituire `play_wake_beep` con la variante async nei call-site di `alexa_custom/stt.py`: wake beeps (≈661, 697, 717, 732), command beep pre-dispatch (≈822), follow-up tone (≈440)
- [x] 2.2 Verificare l'interazione con `flush_ms`: individuare dove il flush post-beep viene applicato e confermare che con il beep async l'eco residua resti coperta dal gate `_playback_active`; adeguare se necessario
- [x] 2.3 Aggiornare/estendere i test pipeline (`tests/`, ScriptedBackend) che asseriscono l'ordine tone→dispatch: il tono è *avviato* al match ma il dispatch non attende la fine

## 3. Config e verifica on-board

- [x] 3.1 Ripristinare `wake_tone: wake` in `conf/config.yaml` (portato a `none` il 2026-07-14 per l'esperimento diagnostico)
- [x] 3.2 Verifica on-board: trigger "chiama assistenza" → nel journal il gap tra `Direct:`/`Command:` e la riga `TTS (Piper/...)` deve restare ≤ ~50 ms con `wake_tone: wake` (baseline sincrona: 1293 ms)
- [x] 3.3 Verifica eco on-board a volume alto: il beep non deve produrre transcript né re-trigger (osservare `DEBUG Transcript:` subito dopo il beep)
- [x] 3.4 `task eval` + test mirati (`uv run pytest tests/test_stt_pipeline*.py` o equivalenti) come gate finale
