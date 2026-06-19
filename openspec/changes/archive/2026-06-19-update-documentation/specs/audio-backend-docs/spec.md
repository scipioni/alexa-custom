## ADDED Requirements

### Requirement: Document AudioWatcher
La documentazione SHALL descrivere la classe AudioWatcher che monitora il grafo PipeWire e riapplica il routing e PCM volume in risposta a eventi di connessione/disconnessione dispositivi.

#### Scenario: AudioWatcher described
- **WHEN** un utente cerca come il sistema gestisce il routing audio
- **THEN** trova descritto AudioWatcher con: monitoraggio eventi PipeWire via pulsectl, _check_and_enforce() su device connect, _restore_hw_pcm() dopo ogni connessione pulsectl

### Requirement: Document PCM restore workaround
La documentazione SHALL descrivere il bug del reset PCM hardware quando pulsectl apre una connessione, e la soluzione `_restore_hw_pcm()`.

#### Scenario: PCM restore bug documented
- **WHEN** un utente cerca perché l'audio diventa silenzioso dopo un'operazione pulsectl
- **THEN** trova descritto: problema (pipewire-pulse resetta ALSA PCM a 0%), soluzione (chiamare _restore_hw_pcm() dopo ogni connessione pulsectl), e regola "mai aprire pulsectl.Pulse() senza chiamare _restore_hw_pcm() dopo"

### Requirement: Document GStreamer capture profiles with STT overrides
La documentazione SHALL descrivere come i profili GStreamer possono sovrascrivere parametri STT (rms_threshold, vad_silence_ms) oltre ai parametri GStreamer.

#### Scenario: Profile STT overrides documented
- **WHEN** un utente configura un profilo audio in `audio.gstreamer.profiles`
- **THEN** la documentazione mostra che ogni profilo può includere `rms_threshold` e `vad_silence_ms` che vengono applicati allo STT quando il profilo è attivo

### Requirement: Document software vs hardware gain
La documentazione SHALL chiarire che `input_gain` è applicato via software (moltiplicazione numpy) e non modifica il mixer hardware ALSA.

#### Scenario: Gain model documented
- **WHEN** un utente cerca come funziona `audio.input_gain`
- **THEN** trova: il gain è software (post-cattura, pre-Vosk), non modifica il PCM hardware ALSA, range 0.0+ con default **1.0** (nessun cambiamento)
