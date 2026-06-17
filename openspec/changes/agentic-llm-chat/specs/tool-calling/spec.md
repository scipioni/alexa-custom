## ADDED Requirements

### Requirement: Tool definitions generated from metadata
The system SHALL generate JSON Schema tool definitions from the existing `_ACTION_PARAMS` and `_WIZARD_ALLOWED_TYPES` metadata in `llm.py`. Each tool definition SHALL include: name, description, and a JSON Schema parameters object.

#### Scenario: All registry actions exposed
- **WHEN** the agentic loop starts
- **THEN** every action type in `_WIZARD_ALLOWED_TYPES` SHALL have a corresponding tool definition with its required params from `_ACTION_PARAMS`

#### Scenario: Schema format matches OpenAI tools API
- **WHEN** tool definitions are generated
- **THEN** each definition SHALL match the JSON Schema format expected by the OpenAI `tools` parameter: `{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}`

### Requirement: Tool descriptions in Italian
The system SHALL include Italian-language descriptions for each tool, using the existing `_ACTION_LABELS` dict in `llm.py`.

#### Scenario: Italian descriptions
- **WHEN** the system prompt language is `it-IT`
- **THEN** tool descriptions SHALL use Italian text from `_ACTION_LABELS`
