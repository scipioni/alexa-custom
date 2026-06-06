## MODIFIED Requirements

### Requirement: Unified config.yaml with env section
The system SHALL load configuration from `config.yaml` when present. The file SHALL support an optional top-level `env:` key containing a flat string-to-string mapping of environment variables. Values in `env:` SHALL be written into `os.environ`, overwriting any existing values. The `wake_words` key SHALL be a list of wake word group objects; each object SHALL have a required string `word` field, an optional `aliases` list of strings, an optional `lang` string (BCP-47, default `it-IT`), and an optional `triggers` list following the existing trigger schema. A top-level `triggers` key SHALL be accepted as a global fallback and MAY be an empty list or absent. An optional top-level `actions_file:` key specifies the path to an `actions.yaml` file whose triggers are merged into the active config at load time. An optional top-level `llm:` key configures the Ollama-backed conversation engine. All other top-level keys are parsed using the existing actions config schema.

#### Scenario: env section populates os.environ
- **WHEN** `config.yaml` contains `env: { LIVEKIT_URL: wss://example.com }`
- **THEN** `os.environ["LIVEKIT_URL"]` equals `"wss://example.com"` after load

#### Scenario: Wake word group with lang field
- **WHEN** a wake word group specifies `lang: en-US`
- **THEN** `config.wake_words[0].lang` equals `"en-US"`

#### Scenario: Wake word group without lang defaults to it-IT
- **WHEN** a wake word group has no `lang` field
- **THEN** `config.wake_words[0].lang` equals `"it-IT"`

#### Scenario: actions_file key accepted
- **WHEN** `config.yaml` contains `actions_file: actions.yaml`
- **THEN** the loader reads and merges `actions.yaml` from the same directory

#### Scenario: llm key accepted and parsed into LLMConfig
- **WHEN** `config.yaml` contains a valid `llm:` block with `host`, `model`, and `backend`
- **THEN** `config.llm` is a populated `LLMConfig` instance

#### Scenario: llm key absent
- **WHEN** `config.yaml` has no `llm:` key
- **THEN** `config.llm` is `None` and no LLM features are activated

#### Scenario: Wake word group with per-group triggers
- **WHEN** a wake word group defines its own `triggers` list
- **THEN** `config.wake_words[0].triggers` is a non-empty list of `Trigger` objects

#### Scenario: Old flat wake_words list rejected
- **WHEN** `config.yaml` contains `wake_words: [galileo, assistente]` (flat strings)
- **THEN** a `ConfigError` is raised with a message indicating the new format is required

## ADDED Requirements

### Requirement: `LLMConfig` dataclass
The system SHALL parse an `llm:` top-level key in `config.yaml` into a `LLMConfig` dataclass with the following fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | str | — | Must be `"ollama"` |
| `host` | str | — | Ollama base URL, e.g. `http://192.168.1.10:11434` |
| `model` | str | — | Model name, e.g. `llama3.2` |
| `context_turns` | int | `10` | Max exchange pairs kept in history |
| `context_window_secs` | int | `60` | Seconds of inactivity before history reset |
| `fallback_on_no_match` | bool | `true` | Route unmatched commands to LLM |
| `learn_commands` | bool | `true` | Enable `llm_learn` action type |
| `system_prompt` | str\|None | `None` | Optional system prompt override |
| `request_timeout` | float | `10.0` | HTTP request timeout in seconds |

#### Scenario: Minimal llm block parsed
- **WHEN** `llm: {backend: ollama, host: "http://localhost:11434", model: llama3.2}`
- **THEN** `config.llm.host` equals `"http://localhost:11434"` and all optional fields have defaults

#### Scenario: Invalid backend rejected
- **WHEN** `llm: {backend: openai, host: "...", model: "..."}`
- **THEN** a `ConfigError` is raised indicating only `"ollama"` is supported
