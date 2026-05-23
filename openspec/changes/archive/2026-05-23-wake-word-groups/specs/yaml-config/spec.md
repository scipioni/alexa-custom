## MODIFIED Requirements

### Requirement: Unified config.yaml with env section
The system SHALL load configuration from `config.yaml` when present. The file SHALL support an optional top-level `env:` key containing a flat string-to-string mapping of environment variables. Values in `env:` SHALL be written into `os.environ`, overwriting any existing values. The `wake_words` key SHALL be a list of wake word group objects; each object SHALL have a required string `word` field, an optional `aliases` list of strings, and an optional `triggers` list following the existing trigger schema. A top-level `triggers` key SHALL be accepted as a global fallback and MAY be an empty list or absent. All other top-level keys are parsed using the existing actions config schema.

#### Scenario: env section populates os.environ
- **WHEN** `config.yaml` contains `env: { LIVEKIT_URL: wss://example.com }`
- **THEN** `os.environ["LIVEKIT_URL"]` equals `"wss://example.com"` after load

#### Scenario: Wake word group with aliases parsed correctly
- **WHEN** `config.yaml` contains a wake word group with `word: galileo` and `aliases: [hey galileo]`
- **THEN** `config.wake_words[0].word` equals `"galileo"` and `config.wake_words[0].aliases` equals `["hey galileo"]`

#### Scenario: Wake word group with per-group triggers
- **WHEN** a wake word group defines its own `triggers` list
- **THEN** `config.wake_words[0].triggers` is a non-empty list of `Trigger` objects

#### Scenario: Wake word group without triggers uses global fallback
- **WHEN** a wake word group has no `triggers` key and the top-level `triggers` list is non-empty
- **THEN** `config.wake_words[0].triggers` is an empty list and `config.triggers` is non-empty

#### Scenario: Old flat wake_words list rejected
- **WHEN** `config.yaml` contains `wake_words: [galileo, assistente]` (flat strings)
- **THEN** a `ConfigError` is raised with a message indicating the new format is required

#### Scenario: config.yaml without env section
- **WHEN** `config.yaml` exists but has no `env:` key
- **THEN** the file is parsed using the actions config schema; `os.environ` is unchanged
