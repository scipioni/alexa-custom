# Capability: Action Dispatch

## Purpose
Map recognized trigger phrases to a sequence of actions.

## Requirements

### Requirement: Config-driven trigger-to-action mapping
The system SHALL load trigger phrases and action sequences from `config.yaml` and, when `actions_file:` is configured, also from `actions.yaml`. Each trigger entry defines a `phrase` (matched against STT output) and a list of `actions` to execute sequentially. Triggers from `actions.yaml` are appended after inline triggers from `config.yaml` in the active list. In addition to local triggers, all recognized phrases SHALL be published to MQTT for external processing. The active trigger list SHALL be updated without process restart when either config file changes on disk.

#### Scenario: Single action on phrase match
- **WHEN** the recognized command matches a configured trigger phrase
- **THEN** all actions in that trigger's `actions` list are executed in order

#### Scenario: Multiple actions on one phrase
- **WHEN** a trigger defines two actions (e.g., telegram + livekit_join)
- **THEN** both actions execute sequentially in the listed order

#### Scenario: No config file present
- **WHEN** neither `config.yaml` nor `actions.yaml` exists at startup
- **THEN** the process behaves as before (auto-connect to LiveKit, no wake word detection)

#### Scenario: Trigger list updated after hot reload of actions.yaml
- **WHEN** a new trigger phrase is appended to `actions.yaml` and the file is saved
- **THEN** the next recognized command is matched against the updated trigger list

#### Scenario: Unmatched command with LLM fallback enabled
- **WHEN** no trigger matches the transcription and `llm.fallback_on_no_match` is `true`
- **THEN** the transcript is routed to the `ConversationEngine` instead of playing the timeout tone

#### Scenario: Unmatched command with LLM not configured
- **WHEN** no trigger matches and `llm:` is absent from `config.yaml`
- **THEN** the timeout tone plays as before

### Requirement: mqtt_publish action type
The system SHALL support an `mqtt_publish` action type that allows publishing a specific `payload` to a specific `topic` on the configured MQTT broker.

#### Scenario: Trigger HA script via MQTT
- **WHEN** an `mqtt_publish` action is executed with `topic: "home/script/lights"` and `payload: "toggle"`
- **THEN** the message is sent to the MQTT broker

### Requirement: Fuzzy phrase matching
The system SHALL match the STT transcription against configured trigger phrases using the configured `matching_algorithm` (defaulting to `token_set_ratio`) applied to phonetically-normalized strings (via `italian_phonetic()`), with a configurable similarity threshold `matching_threshold` (defaulting to 70, on a 0–100 scale). The supported matching algorithms are:
- `token_set_ratio`: Uses `rapidfuzz.fuzz.token_set_ratio` to score trigger phrases, which ignores word ordering and surrounding filler words. Best for conversational commands.
- `levenshtein`: Calculates strict character edit distance and converts it into a percentage similarity score (`(1.0 - (dist / max_len)) * 100`). Best for short reply/phrase matching with low false-positives.
- `ratio`: Uses `rapidfuzz.fuzz.ratio` for strict character alignment matching.

If `rapidfuzz` is unavailable:
- For `levenshtein`, the system SHALL fall back to a built-in pure-Python Levenshtein edit distance implementation and convert it to a similarity score.
- For other algorithms, the system SHALL fall back to `difflib.SequenceMatcher` with a threshold of `0.70` (normalized matching threshold divided by 100) and log a warning.

#### Scenario: Exact phrase match
- **WHEN** the transcription exactly matches a trigger phrase
- **THEN** that trigger is selected

#### Scenario: Inflected phrase match
- **WHEN** the transcription is `"chiamare"` and the trigger phrase is `"chiama"`
- **THEN** the trigger is selected if similarity exceeds the threshold

#### Scenario: No phrase meets threshold
- **WHEN** the transcription similarity to all trigger phrases is below 70
- **THEN** no action is dispatched and the system plays the timeout beep

#### Scenario: Extra words around trigger phrase with token_set_ratio
- **WHEN** the matching_algorithm is `"token_set_ratio"`, the transcription is `"mi chiama subito"`, and the trigger phrase is `"chiama"`
- **THEN** the trigger is selected (token_set_ratio scores the overlap regardless of surrounding tokens)

#### Scenario: Extra words around trigger phrase with levenshtein
- **WHEN** the matching_algorithm is `"levenshtein"`, the transcription is `"mi chiama subito"`, and the trigger phrase is `"chiama"`
- **THEN** the trigger is NOT selected because the strict edit distance lowers the similarity score below the threshold

#### Scenario: Phonetic variant of trigger phrase
- **WHEN** the transcription is `"ke fai"` and the trigger phrase is `"che fai"`
- **THEN** after phonetic normalization both sides compare as `"ke fai"` and the trigger is selected

### Requirement: Reply matching uses strict per-context defaults
Reply phrases in interactive `ask` loops (`on_reply` triggers) SHALL be matched using `recognition.reply_matching_algorithm` (defaulting to `levenshtein`) and `recognition.reply_matching_threshold` (defaulting to 80), independently of the global `matching_algorithm` and `matching_threshold` used for wake-word command matching.

#### Scenario: Reply matching is strict while command matching stays loose
- **WHEN** no matching keys are configured, the transcription is `"mi chiama subito"` against the wake trigger `"chiama"`, and later the reply `"sicuro"` is given against the reply phrase `"si"`
- **THEN** the wake trigger is selected (token_set_ratio default) but the reply does NOT match (strict reply default)

#### Scenario: Reply keys override independently
- **WHEN** `reply_matching_algorithm` is set to `token_set_ratio`
- **THEN** reply matching uses token_set_ratio while wake-command matching continues to follow `matching_algorithm`

### Requirement: Short-phrase exact-match guard
When the phonetically-normalized form of a trigger phrase or alias is shorter than 4 characters, the system SHALL require exact equality with the normalized transcription for that phrase to match (similarity 100 on equality, 0 otherwise), regardless of the configured algorithm and threshold.

#### Scenario: Exact short reply matches
- **WHEN** the reply phrase is `"si"` and the transcription is `"si"` (or `"sì"`, normalizing to the same form)
- **THEN** the reply trigger is selected

#### Scenario: Near-miss short reply does not match
- **WHEN** the reply phrase is `"si"` and the transcription is `"se"`
- **THEN** the reply trigger is NOT selected, even though the edit distance is 1

#### Scenario: Short phrase embedded in longer utterance does not match
- **WHEN** the reply phrase is `"si"` and the transcription is `"si grazie"`
- **THEN** the reply trigger is NOT selected (longer forms must be added as aliases)

### Requirement: livekit_join action type
The system SHALL support a `livekit_join` action type that connects to the configured LiveKit room. If already connected, the action is a no-op. The connection attempt SHALL employ an exponential backoff strategy if the initial connection fails.

#### Scenario: Trigger LiveKit connection
- **WHEN** a `livekit_join` action is dispatched
- **THEN** the LiveKit client connects to the room specified in the action (or `LIVEKIT_ROOM` env var if not specified)

#### Scenario: Already connected
- **WHEN** a `livekit_join` action is dispatched and a LiveKit session is active
- **THEN** the action is skipped and a debug log entry is written

#### Scenario: Connection failure backoff
- **WHEN** a `livekit_join` action is dispatched and the connection fails
- **THEN** the system SHALL wait before retrying, doubling the wait time on each subsequent failure (e.g., 2s, 4s, 8s) up to a maximum delay of 30 seconds.

### Requirement: say action type
The system SHALL support a `say` action type in the trigger sequence. This action converts a provided `text` parameter into audible speech using the configured TTS backend.

#### Scenario: Sequence with voice feedback
- **WHEN** a trigger defines multiple actions starting with `say`
- **THEN** the system speaks the text first, then proceeds to subsequent actions (e.g., telegram or livekit_join)

### Requirement: set_volume_from_transcript action type
The system SHALL support a `set_volume_from_transcript` action type that receives the raw STT transcript, extracts a volume percentage, and sets the system output volume. This SHALL use the existing `set_output_volume()` function and `save_volume_state()` for persistence.

#### Scenario: Action dispatched with transcript
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "volume al 80%"
- **THEN** the system extracts 80%, calls `set_output_volume(0.80)`, and saves the new volume state

#### Scenario: Transcript without recognizable number
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "alza il volume"
- **THEN** the action SHALL be a no-op (no volume change, no error)

#### Scenario: Volume at minimum
- **WHEN** a `set_volume_from_transcript` action is dispatched with transcript "volume al 0%"
- **THEN** volume is set to 0.0 (muted)

### Requirement: Graceful unknown action type
The system SHALL log a warning and skip any action entry with an unrecognized `type` field, without crashing or halting other actions in the sequence.

#### Scenario: Unknown action type in config
- **WHEN** the config file contains `type: sms` (not implemented)
- **THEN** a warning is logged and the next action in the sequence continues
