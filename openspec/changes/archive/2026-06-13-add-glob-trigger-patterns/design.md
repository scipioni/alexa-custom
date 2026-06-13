## Context

Stage-2 command matching lives in `match_trigger()` (`alexa_custom/actions.py`). It scores the captured transcript against each trigger's `phrase` + `aliases` using `italian_phonetic()` normalization and `get_similarity_score()` (rapidfuzz, with pure-Python fallbacks), selecting the best trigger above `matching_threshold`. Triggers come from `config.Trigger` (`phrase`, `actions`, `aliases`), parsed in `config.py`.

This change adds an optional `patterns` field to `Trigger` and a word-glob matcher that runs ahead of fuzzy scoring. Stage 1 (wake detection), `capture_transcript`, and all timing behavior are untouched — the matcher operates only on the already-captured command string.

## Goals / Non-Goals

**Goals:**
- Let one trigger express a family of phrasings via a word-glob pattern (`accend* * luci`).
- Keep the phonetic robustness of the existing matcher — literal pattern tokens match phonetically, not letter-for-letter.
- Make a pattern hit definitive and precedence-ordered before fuzzy scoring.
- Zero behavior change for triggers that define no `patterns`.

**Non-Goals:**
- No time-window / "in N seconds" constraint, per-rule window, or word timestamps.
- No changes to stage-2 capture, stage-1 wake detection, or always-on detection.
- No raw regular-expression syntax — `*` is a glob wildcard only.

## Decisions

### Word-glob DSL over raw regex
`*` denotes a glob wildcard (word-prefix/infix, or a standalone "any words" gap), not a regex quantifier. Rationale: the user's intent (`accend*` = "word starting with accend") is glob semantics; raw `re` would read `accend*` as "accen" + zero-or-more "d" and would match against literal characters, discarding the phonetic layer that makes the system robust to STT noise. Alternative considered: full `re.search` on the raw transcript — rejected as brittle and surprising.

### Tokens matched phonetically
Each literal pattern token and each transcript word are reduced via `italian_phonetic()` before comparison. A bare literal token must clear `matching_threshold` against a transcript word (reusing `get_similarity_score` with `matching_algorithm`); a `foo*` token matches when the transcript word's phonetic form *starts with* the token prefix's phonetic form. This preserves the `luci`≈`luce` tolerance the rest of the system relies on. Alternative considered: exact string `startswith` — rejected; loses STT-noise tolerance.

### Matcher = fuzzy ordered-subsequence walk
Pattern tokens are aligned left-to-right over the transcript token list. A standalone `*` consumes zero-or-more transcript words greedily-but-backtrackable so later anchors can still align. A literal/`foo*` token advances the transcript cursor to the next satisfying word. The pattern matches iff all tokens are consumed in order. This naturally implements "anchors in order, gaps anywhere between."

### Precedence and return contract
`match_trigger()` iterates triggers; for each with `patterns`, it tests the globs first. The first trigger whose pattern matches is returned immediately (treated as definitive). If no pattern matches across all triggers, the existing fuzzy best-score selection runs unchanged over the full trigger list. Keeping a single entry point avoids a second matching pass at call sites in `stt.py`.

### Config surface
`Trigger` gains `patterns: list[str] = field(default_factory=list)`. Parsing in `config.py` reads an optional `patterns` key (list of strings), validating type like `aliases`. Absent key → empty list → today's behavior.

## Risks / Trade-offs

- **Pattern too permissive → false matches** → `*` gaps plus phonetic tolerance can over-match short patterns. Mitigation: require literal anchor tokens to clear `matching_threshold`; document that very short single-token patterns behave like a loose keyword. Authoring guidance in config comments.
- **Precedence masks a better fuzzy match** → a pattern hit wins even if another trigger scored higher. This is intended (patterns are explicit author intent), but noted so it is not surprising; documented in the spec.
- **Backtracking cost** → ordered-subsequence with `*` is worst-case quadratic in token count. Transcripts and patterns are short (a handful of words), so cost is negligible on the target board.
- **Ambiguous `*` semantics** (in-word vs standalone) → resolved by token position: a token equal to `*` is a gap; a token containing `*` elsewhere is an in-word glob. Documented in the spec scenarios.
