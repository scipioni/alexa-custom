# Capability: Secrets Config

## Purpose
Keep credentials, API keys, and sensitive URLs secure by storing them in a dedicated secrets file outside of standard configuration.

## Requirements

### Requirement: conf/secrets.yaml schema
The system SHALL support a `conf/secrets.yaml` file with the following optional top-level keys:

- `livekit`: mapping with `url` (str), `api_key` (str), `api_secret` (str), `room` (str)
- `telegram`: mapping with `bot_token` (str), `chat_id` (str)
- `llm`: mapping with `host` (str) — the Ollama base URL
- `mqtt`: mapping with `username` (str, optional) and `password` (str, optional)

All top-level keys are optional. Missing keys result in the corresponding subsystem having no credentials.

#### Scenario: Full secrets file parsed
- **WHEN** `conf/secrets.yaml` contains all four top-level sections with valid values
- **THEN** `load_secrets()` returns a `SecretsConfig` with all fields populated

#### Scenario: Partial secrets file
- **WHEN** `conf/secrets.yaml` contains only `livekit:` and no `telegram:` key
- **THEN** `secrets.telegram` is `None` and `secrets.livekit` is populated

#### Scenario: Missing secrets file
- **WHEN** `conf/secrets.yaml` does not exist
- **THEN** `load_secrets()` returns an empty `SecretsConfig` and logs a warning; the daemon starts normally

### Requirement: Secrets applied to os.environ at startup
`load_secrets()` SHALL apply credentials to `os.environ` immediately after parsing, before any subsystem initialises. The mapping SHALL be:

| secrets.yaml key | os.environ key |
|---|---|
| `livekit.url` | `LIVEKIT_URL` |
| `livekit.api_key` | `LIVEKIT_API_KEY` |
| `livekit.api_secret` | `LIVEKIT_API_SECRET` |
| `livekit.room` | `LIVEKIT_ROOM` |
| `telegram.bot_token` | `TELEGRAM_BOT_TOKEN` |
| `telegram.chat_id` | `TELEGRAM_CHAT_ID` |
| `llm.host` | *(not injected — passed via LLMConfig.host from secrets merge)* |
| `mqtt.username` | `MQTT_USERNAME` |
| `mqtt.password` | `MQTT_PASSWORD` |

#### Scenario: LiveKit credentials injected into os.environ
- **WHEN** `conf/secrets.yaml` contains `livekit.url: wss://example.livekit.cloud`
- **THEN** `os.environ["LIVEKIT_URL"]` equals `"wss://example.livekit.cloud"` before the LiveKit client initialises

#### Scenario: Credential values not logged
- **WHEN** `load_secrets()` applies credentials
- **THEN** log lines reference only the key names (e.g., "Applied: LIVEKIT_URL"), never the values

### Requirement: LLM host merged from secrets into LLMConfig
The `llm.host` from `conf/secrets.yaml` SHALL be merged into the `LLMConfig` parsed from `conf/config.yaml`. If `llm:` is present in `config.yaml` but `llm.host` is absent from `secrets.yaml`, the daemon SHALL log a warning and disable LLM features.

#### Scenario: LLM host merged
- **WHEN** `secrets.yaml` has `llm.host: http://192.168.1.10:11434` and `config.yaml` has an `llm:` block
- **THEN** `config.llm.host` equals `"http://192.168.1.10:11434"`

#### Scenario: LLM configured but no host in secrets
- **WHEN** `config.yaml` has an `llm:` block and `secrets.yaml` has no `llm:` key
- **THEN** `config.llm` is set to `None`, a warning is logged, and LLM actions do nothing

### Requirement: Secrets not hot-reloaded
`conf/secrets.yaml` SHALL NOT be watched by the hot-reload watcher. Changes to credentials require a daemon restart.

#### Scenario: Secrets file changed while daemon runs
- **WHEN** `conf/secrets.yaml` is edited and saved while the daemon is running
- **THEN** the daemon continues using the original credential values; no reload occurs
