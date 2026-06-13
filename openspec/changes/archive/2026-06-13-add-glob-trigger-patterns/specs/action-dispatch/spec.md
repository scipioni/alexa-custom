## ADDED Requirements

### Requirement: Word-glob trigger patterns

A trigger MAY define an optional `patterns` list of word-glob strings in addition to (or instead of) its `phrase` and `aliases`. When matching a transcription, the system SHALL evaluate a trigger's `patterns` before fuzzy phrase matching; a pattern match is definitive and selects that trigger immediately, bypassing similarity scoring. A trigger with no `patterns`, or whose patterns do not match, SHALL fall back to fuzzy phrase matching unchanged.

A word-glob pattern is a sequence of space-separated tokens, evaluated against the space-separated tokens of the phonetically-normalized transcription:

- A literal token (e.g. `luci`) matches a transcription word whose phonetic similarity (via `italian_phonetic()` and the configured `matching_algorithm`) meets `matching_threshold`.
- A token ending in `*` (e.g. `accend*`) matches a transcription word whose phonetic form begins with the phonetic form of the token's literal prefix. The `*` is a glob wildcard (prefix/infix within a word), NOT a regular-expression quantifier.
- A standalone `*` token matches any number of intervening transcription words, including zero.
- Pattern tokens SHALL be aligned in order over the transcription tokens (a fuzzy ordered-subsequence walk); a pattern matches only if every pattern token is satisfied in sequence.

#### Scenario: Glob pattern with prefix wildcard and word gap

- **WHEN** a trigger defines `patterns: ["accend* * luci"]` and the transcription is `"accendi le luci del salotto"`
- **THEN** the trigger is selected (`accend*` matches `accendi`, the standalone `*` swallows `le`, `luci` matches `luci`)

#### Scenario: Glob pattern with no intervening words

- **WHEN** a trigger defines `patterns: ["accend* * luci"]` and the transcription is `"accendimi le luci"`
- **THEN** the trigger is selected (the standalone `*` matches the single word `le`, and `accend*` matches `accendimi`)

#### Scenario: Phonetic tolerance on a literal pattern token

- **WHEN** a trigger defines `patterns: ["accend* * luci"]` and the transcription word for `luci` is recognized as `"luce"`
- **THEN** the trigger is still selected because `luce` clears the phonetic similarity threshold against `luci`

#### Scenario: Pattern match takes precedence over fuzzy scoring

- **WHEN** one trigger's `patterns` matches the transcription and another trigger would score higher under fuzzy phrase matching
- **THEN** the pattern-matched trigger is selected

#### Scenario: Pattern does not match, fuzzy fallback applies

- **WHEN** a trigger's `patterns` do not match the transcription
- **THEN** the system evaluates that trigger's `phrase` and `aliases` via fuzzy phrase matching as if no patterns were defined

#### Scenario: Required order not satisfied

- **WHEN** a trigger defines `patterns: ["accend* * luci"]` and the transcription is `"luci accendi"`
- **THEN** the pattern does not match (tokens must align in order)

## MODIFIED Requirements

### Requirement: Fuzzy phrase matching
The system SHALL match the STT transcription against configured trigger phrases using the configured `matching_algorithm` (defaulting to `token_set_ratio`) applied to phonetically-normalized strings (via `italian_phonetic()`), with a configurable similarity threshold `matching_threshold` (defaulting to 70, on a 0–100 scale). Fuzzy phrase matching is the fallback path: it SHALL be applied only when a trigger defines no `patterns`, or when its `patterns` do not match the transcription (see "Word-glob trigger patterns"). The supported matching algorithms are:
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
