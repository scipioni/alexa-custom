## ADDED Requirements

### Requirement: Document all CLI entry points
La documentazione SHALL elencare tutti i comandi CLI definiti in `[project.scripts]` in pyproject.toml, raggruppati per categoria (daemon, audio, STT, utility).

#### Scenario: Daemon CLI documented
- **WHEN** un utente cerca come avviare il sistema
- **THEN** trova: `alexa-client [--web-port PORT]` (main daemon), `serena` (alias), `alexa-setup` (download modelli STT/TTS)

#### Scenario: Audio CLI documented
- **WHEN** un utente cerca comandi audio
- **THEN** trova: `alexa-audio` (loopback test), `alexa-devices` (lista dispositivi), `alexa-audio-setup` (configurazione audio NewPie), `alexa-audio-doctor` (diagnostica audio), `serena-test` (test audio)

#### Scenario: STT/Utility CLI documented
- **WHEN** un utente cerca utility STT
- **THEN** trova: `serena-stt` (STT CLI), `alexa-wake-eval` (valutazione wake word), `alexa-record` (registrazione)

### Requirement: Document all task commands
La documentazione SHALL elencare tutti i comandi task con descrizione.

#### Scenario: Task commands listed
- **WHEN** un utente esegue `task --list`
- **THEN** la documentazione riflette esattamente i task disponibili: sviluppo (test, lint, format, fix, run, start), audio (audio:setup, audio:restart, audio:status, audio:doctor, audio:test), display (display:compile, display:test, display:setup, display:flash), STT (test-stt-e2e, eval, stt:analyze-dumps), release (release:patch, release:minor, release:major, release:rollback), setup (setup, setup:gstreamer), clean
