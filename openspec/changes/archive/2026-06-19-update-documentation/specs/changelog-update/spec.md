## ADDED Requirements

### Requirement: Update CHANGELOG.md with missing entries
CHANGELOG.md SHALL contenere tutte le modifiche non ancora registrate, dalla versione 0.3.0 in poi, includendo: GStreamer capture profiles, OpenAI LLM backend, call_tone option, RMS threshold profile overrides, serena-stt CLI, display feature, follow-up conversation mode, sleeping mode, web config panel, phonetic matching, trigger patterns.

#### Scenario: Changelog entries present
- **WHEN** un utente legge CHANGELOG.md
- **THEN** trova voci per: GStreamer capture backend con webrtcdsp, profili di cattura audio con switching vocale, backend LLM openai, call_tone per toni chiamata, RMS threshold da profili audio, comando serena-stt, display feedback visivo, follow-up conversation mode, sleeping mode (stop_listening/start_listening), web config panel, italian phonetic matching, word-glob trigger patterns, direct triggers with_wake, AudioWatcher, PCM restore dopo pulsectl

### Requirement: Use conventional changelog format
CHANGELOG.md SHALL usare il formato Keep a Changelog con sezioni Added, Fixed, Changed.

#### Scenario: Format consistent
- **WHEN** un utente esamina CHANGELOG.md
- **THEN** le voci sono raggruppate per versione con tag data, sezioni Added/Fixed/Changed, e formattazione Markdown
