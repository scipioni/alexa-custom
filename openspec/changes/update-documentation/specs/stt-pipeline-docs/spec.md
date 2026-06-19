## ADDED Requirements

### Requirement: Document STT pipeline architecture
La documentazione SHALL descrivere il pipeline STT a modello singolo (Vosk free-vocabulary) con capture backend configurabile (parec o GStreamer).

#### Scenario: Single-model architecture described
- **WHEN** un nuovo sviluppatore legge docs/stt-simple.md
- **THEN** trova un diagramma del pipeline che mostra: mic → capture backend (parec|gstreamer) → Vosk decode → trigger matching → action dispatch

#### Scenario: Capture backend documented
- **WHEN** un nuovo sviluppatore cerca informazioni sul backend di cattura
- **THEN** trova documentati entrambi i backend: `parec` (default) e `gstreamer` (con webrtcdsp per noise suppression, AGC, high-pass filter, compressor)

### Requirement: Document audio capture profiles
La documentazione SHALL descrivere i profili di cattura audio definiti sotto `audio.gstreamer.profiles` e il loro switching a runtime tramite l'action `set_audio_profile`.

#### Scenario: Profile switching documented
- **WHEN** un utente configura `set_audio_profile` nei trigger
- **THEN** la documentazione spiega che ogni profilo può sovrascrivere parametri GStreamer (noise_suppression_level, agc_target_level_dbfs, agc_compression_gain_db) E parametri STT (rms_threshold, vad_silence_ms)

### Requirement: Document trigger matching con pattern glob
La documentazione SHALL descrivere il matching a due fasi: word-glob patterns (definitivo) + fuzzy phonetic scoring (fallback).

#### Scenario: Pattern matching documented
- **WHEN** un utente legge la sezione trigger matching
- **THEN** trova esempi di pattern glob con `*`, `accend*`, token fonetici, e ordinamento sequence-subsequence

### Requirement: Document direct triggers, sleeping mode, follow-up
La documentazione SHALL coprire: `with_wake: false` per attivazione senza wake word, le action `stop_listening`/`start_listening`, e la modalità follow-up conversation.

#### Scenario: Direct triggers documented
- **WHEN** un utente cerca come attivare comandi senza wake word
- **THEN** trova `with_wake: false` documentato con esempi e note sul matching più restrittivo

### Requirement: Document backend benchmark
La documentazione SHALL includere i dati di benchmark che giustificano la scelta di Vosk come unico backend supportato.

#### Scenario: Benchmark data present
- **WHEN** un utente valuta il backend STT
- **THEN** trova la tabella comparativa Vosk vs sherpa-onnx con metriche: model load time, CPU usage, RTF p95, endpoint latency p95, qualità trascrizione
