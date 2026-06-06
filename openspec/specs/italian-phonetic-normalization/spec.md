# Capability: Italian Phonetic Normalization

## Purpose
Provide a deterministic phonetic normalization function for Italian text, enabling fuzzy matching that is robust to spelling variants, geminate consonants, and digraph differences.

## Requirements

### Requirement: Italian phonetic normalization function
The system SHALL provide an `italian_phonetic(text: str) -> str` function that applies `normalize_text()` first and then rewrites the result using the following deterministic rules, in order:
1. Geminate consonants reduced to single: `bb`→`b`, `cc`→`c`, `dd`→`d`, `ff`→`f`, `gg`→`g`, `ll`→`l`, `mm`→`m`, `nn`→`n`, `pp`→`p`, `rr`→`r`, `ss`→`s`, `tt`→`t`, `vv`→`v`, `zz`→`z`.
2. Trigraph `gli` → `li`.
3. Digraph `gn` → `n`.
4. `sch` before any vowel → `sk`.
5. `sci` → `si`, `sce` → `se`.
6. `ch` before `e` or `i` → `k` (e.g., `che`→`ke`, `chi`→`ki`).
7. `gh` before `e` or `i` → `g` (e.g., `ghe`→`ge`, `ghi`→`gi`).
8. `qu` → `k`.

#### Scenario: Geminate reduction
- **WHEN** `italian_phonetic("bello")` is called
- **THEN** the result is `"belo"`

#### Scenario: ch digraph before e
- **WHEN** `italian_phonetic("che")` is called
- **THEN** the result is `"ke"`

#### Scenario: gli trigraph
- **WHEN** `italian_phonetic("figlio")` is called
- **THEN** the result is `"filio"`

#### Scenario: Idempotent on already-normalized text
- **WHEN** `italian_phonetic("chiama")` is called twice
- **THEN** both calls return the same string

#### Scenario: Diacritics stripped before phonetic rules
- **WHEN** `italian_phonetic("sì")` is called
- **THEN** the result is `"si"` (diacritic stripped by normalize_text, no phonetic rules apply)
