# Capability: LLM Command Learning

## Purpose
Elicit, synthesize, and persist new user commands entirely through natural voice interaction backed by an LLM parser.

## Requirements

### Requirement: `llm_learn` action type triggers the command wizard
The system SHALL support an `llm_learn` action type that starts the `LearnWizard` — a multi-turn voice dialogue that elicits a trigger phrase and one or more chained actions, confirms with the user, then persists the new command to `actions.yaml`. The wizard SHALL be associated with the wake word group that dispatched the `llm_learn` action; the learned command is saved under that group's key in `wake_triggers`.

#### Scenario: Wizard invoked via explicit trigger
- **WHEN** the user says the wake word followed by a phrase that dispatches `type: llm_learn`
- **THEN** the LearnWizard starts and asks for the trigger phrase

#### Scenario: Learned command saved under active wake word group
- **WHEN** the `llm_learn` action was dispatched by wake word group `galileo`
- **THEN** the new trigger is appended to `wake_triggers.galileo` in `actions.yaml`

### Requirement: Wizard elicits trigger phrase and chained actions
The `LearnWizard` SHALL guide the user through a structured dialogue:
1. Ask for the trigger phrase
2. Ask what action(s) to perform (free-form; LLM interprets intent)
3. For each identified action, ask for required parameters
4. Read back a full summary and request confirmation
5. On confirmation, write to `actions.yaml`

Allowed action types for the wizard: `say`, `tone`, `shell`, `mqtt_publish`, `telegram`, `livekit_join`. The wizard SHALL NOT generate `ask`, `llm_chat`, or `llm_learn` actions.

#### Scenario: Single-action command learned
- **WHEN** the user says phrase "buonanotte" and action "di' buonanotte"
- **THEN** the wizard produces `{phrase: "buonanotte", actions: [{type: say, text: "Buonanotte!"}]}`

#### Scenario: Multi-action command learned
- **WHEN** the user specifies "di' buonanotte e spegni le luci"
- **THEN** the wizard elicits params for both `say` and `mqtt_publish` and produces a trigger with two actions

#### Scenario: Unsupported action type requested
- **WHEN** the user asks for an action type not in the allowed list (e.g., `ask`)
- **THEN** the wizard informs the user that this type must be configured manually and re-prompts

### Requirement: Wizard confirms before persisting
After collecting all parameters, the `LearnWizard` SHALL speak a full summary of the new command and ask for explicit confirmation ("confermi?"). The wizard SHALL only write to `actions.yaml` if the user responds affirmatively.

#### Scenario: User confirms
- **WHEN** the wizard reads back the summary and the user says "sì" or equivalent
- **THEN** the trigger is appended to `actions.yaml` and the wizard speaks "Comando salvato"

#### Scenario: User cancels
- **WHEN** the user says "no" or "annulla" at the confirmation step
- **THEN** nothing is written and the wizard speaks "Operazione annullata"

#### Scenario: Confirmation timeout
- **WHEN** the user does not respond within the confirmation timeout
- **THEN** nothing is written and the wizard speaks "Operazione annullata"

### Requirement: Learned commands are immediately active
After a successful write to `actions.yaml`, the hot-reload watcher SHALL pick up the change within `config_poll_interval` seconds (default 4 s) and the new trigger SHALL be dispatchable without restart.

#### Scenario: Immediate availability after learning
- **WHEN** the user confirms a new command and the hot-reload interval elapses
- **THEN** speaking the learned phrase triggers the associated actions

### Requirement: Learned command block is visually separated in `actions.yaml`
The first time `ActionsFileStore` appends a learned command, it SHALL insert a `# --- learned commands ---` comment separator before the new entry if none exists. Subsequent writes append within the same block.

#### Scenario: First learned command adds separator
- **WHEN** `actions.yaml` contains only hand-written triggers and the first command is learned
- **THEN** a `# --- learned commands ---` comment appears above the new entry
