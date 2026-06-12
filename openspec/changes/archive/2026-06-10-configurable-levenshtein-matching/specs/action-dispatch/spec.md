## MODIFIED Requirements

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
