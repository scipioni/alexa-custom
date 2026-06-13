## ADDED Requirements

### Requirement: Phonetic normalisation for Italian wake words

The system SHALL apply Italian-specific phonetic normalisation to both the recognised text and alias phrases before Levenshtein comparison.

The normalisation MUST:
- Collapse double consonants to single
- Normalise palatal clusters: `sci→si`, `sce→se`, `gli→li`, `gni→ni`, `gn→n`
- Normalise velar+palatal clusters: `chi→ci`, `che→ce`, `ghi→gi`, `ghe→ge`
- Accept optional leading `a-` prefix (fast-speech elision)

#### Scenario: Double consonant confusion is normalised

- **WHEN** the recognised text contains "ascoltami assistente" (correct)
- **THEN** the matcher returns a hit against the alias "ascoltami assistente"

#### Scenario: Common Italian palatal confusion is normalised

- **WHEN** the recognised text contains "ascolta insistente" (STT error: `assistente→insistente`)
- **THEN** the matcher returns a hit for wake phrase "ascoltami assistente"

#### Scenario: Word boundary error is handled

- **WHEN** the recognised text contains "ascolta mi assistente" (STT split "ascoltami" into two words)
- **THEN** the matcher returns a hit for wake phrase "ascoltami assistente"

### Requirement: Levenshtein-based wake word matching

The system SHALL use `rapidfuzz.fuzz.ratio` to compute normalised Levenshtein similarity between phonetically normalised recognised text and alias phrases.

The matcher SHALL test a sliding window of word counts from the recognised text to find the best alignment with the alias phrase.

A match SHALL fire when the best ratio across all alias phrases is ≥ the configured `phonetic_threshold`.

#### Scenario: Above-threshold phonetic match fires

- **WHEN** recognised text = "scoltami assistente" and wake phrase = "ascoltami assistente"
- **AND** phonetic threshold = 0.6
- **THEN** the matcher returns the WakeWordGroup with command extracted from the residual text

#### Scenario: Below-threshold phonetic match is rejected

- **WHEN** recognised text = "arresta il sistema" and wake phrase = "ascoltami assistente"
- **AND** phonetic threshold = 0.6
- **THEN** the matcher returns None (no wake word detected)

### Requirement: Configurable phonetic matching

The system SHALL provide two configuration knobs in the `recognition` section of `config.yaml`:

- `phonetic_matching`: bool, default `true` — enable/disable phonetic fallback for Vosk free-vocab
- `phonetic_threshold`: float, default `0.6` — minimum Levenshtein ratio for a phonetic match

#### Scenario: Phonetic matching can be disabled

- **WHEN** `phonetic_matching` is set to `false`
- **THEN** the system uses exact matching only, even for Vosk free-vocab

#### Scenario: Threshold is configurable

- **WHEN** `phonetic_threshold` is set to `0.8`
- **THEN** only close phonetic matches (ratio ≥ 0.8) are accepted

### Requirement: Phonetic match does not break exact matching

The system SHALL always try exact normalised matching first. Phonetic matching SHALL only fire when exact match fails.

#### Scenario: Exact match still takes priority

- **WHEN** the recognised text is an exact match for an alias phrase
- **THEN** the exact match path returns the result without invoking Levenshtein
