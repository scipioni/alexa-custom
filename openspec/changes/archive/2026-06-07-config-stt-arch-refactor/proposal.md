## Why

The project has grown to include STT, TTS, LLM, MQTT, audio hardware, LiveKit, Telegram, and a web dashboard — all configured through a single flat `config.yaml` with no clear separation between credentials, hardware settings, behavioral config, and user commands. Credentials live alongside volume knobs, the STT backend is shared between wake-word detection and command recognition even though those stages have different accuracy/CPU tradeoffs, and there is no way to add more action files without editing config. This refactor imposes a rational structure before complexity compounds further.

## What Changes

- **BREAKING** `config.yaml` moves to `conf/config.yaml`; structure changes to nested blocks (`audio:`, `stt:`, `tts:`, `llm:`, `mqtt:`, `web:`, `system:`, `recognition:`) — flat legacy keys removed
- **BREAKING** `env:` section removed; credentials move to git-ignored `conf/secrets.yaml`
- **BREAKING** `actions_file:` (single file) replaced by `actions.dir:` pointing to `conf/actions/` directory
- **BREAKING** `stt.backend` replaced by `stt.stage1.backend` + `stt.stage2.backend` — wake-word detection and command recognition can now use different STT engines
- New `conf/actions/system.yaml` shipped with predefined commands (time, date, restart, llm_chat, llm_learn); loaded first with highest match priority
- New `conf/actions/learned.yaml` as the dedicated write target for the `llm_learn` action
- `on_startup` defined exclusively in `system.yaml`; other action files cannot define it
- All `.yaml` files in `conf/actions/` auto-discovered; `system.yaml` always loaded first, remainder sorted alphabetically
- `recognition.confidence` (was `wake_confidence`) moves under `stt.stage1.confidence` — it is a stage-1 Vosk scoring parameter, not a top-level recognition setting
- Hot-reload watches `conf/config.yaml` and all files in `conf/actions/`; `conf/secrets.yaml` requires restart

## Capabilities

### New Capabilities
- `conf-layout`: `conf/` directory structure — secrets, config, and actions sub-directory with auto-discovery
- `secrets-config`: `conf/secrets.yaml` schema for credentials (LiveKit, Telegram, LLM host, MQTT auth); applied to `os.environ` at startup; excluded from hot-reload
- `multi-stage-stt`: Independent STT backend configuration for stage 1 (wake-word detection) and stage 2 (command recognition), with separate model paths and stage-1-specific VAD parameters
- `multi-action-files`: Auto-discovery of all `.yaml` files in `conf/actions/`; `system.yaml` always first; first-match-wins merge of triggers and wake_triggers; single writable `learned.yaml` for the learning agent

### Modified Capabilities
- `yaml-config`: Config file location changes to `conf/config.yaml`; `env:` section removed; all top-level flat keys replaced by nested blocks; audio, STT, TTS, LLM, MQTT, web, system settings each get their own sub-section
- `actions-file`: Single `actions_file:` path replaced by directory-based multi-file discovery; `on_startup` restricted to `system.yaml`; `wake_triggers` merged across all files per wake word
- `wake-word-detection`: STT pipeline gains two distinct backend instances — stage 1 for continuous wake-word listening, stage 2 for command capture after wake

## Impact

- `alexa_custom/config.py`: near-complete rewrite — new sub-dataclasses (`AudioConfig`, `STTConfig`, `TTSConfig`, `RecognitionConfig`, `MQTTConfig`, `WebConfig`, `SystemConfig`, `SecretsConfig`, `STTStage1Config`, `STTStage2Config`), new `load_secrets()`, `_load_actions_dir()`, removal of `env:` injection, removal of legacy flat key aliases
- `alexa_custom/stt.py`: `run_stt_worker` loads two backends; `_recognition_loop` and `_wake_detected` receive separate `stage1_backend` / `stage2_backend` arguments
- `alexa_custom/config_manager.py`: watcher extended to monitor `conf/actions/` directory in addition to `conf/config.yaml`
- `alexa_custom/actions.py`: `llm_learn` action writes to `config.learn_file` instead of `config.actions_file`
- `alexa_custom/audio.py`, `tts.py`, `web.py`, `client.py`: update attribute access to use sub-config objects (`config.audio.output_volume`, `config.tts.backend`, etc.)
- `conf/` directory created; `config.yaml`, `actions.yaml`, `actions.yaml.example` retired at project root
- `.gitignore`: add `conf/secrets.yaml`
- `setup/`, `Taskfile.yml`: path references updated
- Tests: fixtures updated for new config shape
