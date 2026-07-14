## Context

Currently, the trigger phrase matcher is hardcoded to use `rapidfuzz.fuzz.token_set_ratio` with a fallback to `difflib.SequenceMatcher` if `rapidfuzz` is not installed, running at a fixed threshold of 70. This configuration is optimized for natural command-level inputs (bag of words, word order changes, extra words). However, for short, strict reply phrases in interactive `ask` loops (like "si", "no"), this approach is too loose and prone to false-positives or mismatching. 

To resolve this, we will introduce a configurable matching algorithm under the `recognition` block of the configuration schema, allowing developers to switch matching strategies (e.g. to a Levenshtein character-edit distance model) on a global basis.

## Goals / Non-Goals

**Goals:**
- Make the trigger-matching algorithm configurable via `recognition.matching_algorithm` supporting `token_set_ratio`, `levenshtein`, and `ratio`.
- Make the similarity threshold configurable via `recognition.matching_threshold`.
- Give reply matching in `ask` loops its own algorithm/threshold (`reply_matching_algorithm`, `reply_matching_threshold`) with strict defaults — the global knob alone cannot serve both long commands and short replies, which is the motivating problem.
- Behave sanely on very short phrases, where percentage thresholds are effectively binary.
- Provide a robust pure-Python fallback for Levenshtein edit distance when `rapidfuzz` is not available, avoiding runtime crashes or external build tool requirements.

**Non-Goals:**
- Supporting per-trigger matching algorithm overrides (matching granularity is per-context — wake commands vs replies — not per-trigger).
- Changing phonetic normalization logic (`italian_phonetic()`); the matching continues to use the phonetically-normalized forms of the strings.

## Decisions

### Decision 1: Pure-Python Levenshtein Edit Distance Fallback
To remain architectural-safe, portable, and compile-free, we will implement a standard dynamic programming Levenshtein distance algorithm in `alexa_custom/actions.py` to calculate character-level edit distance.
- *Why:* If `rapidfuzz` (which is a compiled C++ extension package) is absent, falling back to a pure-Python Levenshtein ensures the system remains functional on minimal headless platforms (e.g., Raspberry Pi Zero or older Snapdragon boards with 1GB RAM) without installing heavy build chains (`gcc`, `g++`, etc.).
- *Alternative Considered:* Falling back to standard `difflib.SequenceMatcher` for Levenshtein requests. Rejected because `difflib` uses Gestalt Pattern Matching, which produces different ratios than a normalized Levenshtein distance, violating the requirement of strict edit-distance behavior.

### Decision 2: Levenshtein Percentage Normalization Formula
The Levenshtein edit distance integer $d$ between two strings $s_1$ and $s_2$ will be converted to a percentage similarity score using:
$$score = \left(1.0 - \frac{d}{\max(|s_1|, |s_2|)}\right) \times 100$$
- *Why:* This standard normalization formula mirrors the 0–100 scale used by `rapidfuzz.fuzz` and `difflib.SequenceMatcher`, allowing unified threshold handling across all algorithms.

### Decision 3: Dynamically Passing Config Parameters to `match_trigger()`
`match_trigger()` in `alexa_custom/actions.py` will accept optional `algorithm` and `threshold` arguments. The calling sites in `stt.py` (`_single_stage_loop` and `_wake_detected`) will pass these parameters dynamically from the current configuration:
```python
trigger = match_trigger(
    transcript, 
    triggers, 
    algorithm=config.recognition.matching_algorithm,
    threshold=config.recognition.matching_threshold
)
```
- *Why:* Keeps `actions.py` decoupled from direct knowledge of the config loading sequence, making `match_trigger()` highly testable.

### Decision 4: Per-Context Defaults — Reply Matching Is Strict by Default
Reply matching (`match_trigger(transcript, action.on_reply)` in `_run_action`, `alexa_custom/actions.py:353`) uses `recognition.reply_matching_algorithm` (default `levenshtein`) and `recognition.reply_matching_threshold` (default `80`), independent of the global keys used by the wake-trigger call sites in `stt.py`.
- *Why:* The motivating problem is contextual: long natural-language commands need bag-of-tokens tolerance, short `ask` replies ("si", "no") need strict matching. A single global setting can only fix one side. With per-context defaults, the problem is solved out of the box with zero configuration — the global keys remain available for tuning wake-command matching.
- *Why a higher default threshold (80):* Replies typically gate confirmations (sometimes destructive actions); false-positives are worse than asking again.
- *Alternative Considered:* Per-trigger overrides. Rejected as config-heavy for a need that splits cleanly along the two call-site contexts.

### Decision 5: Short-Phrase Exact-Match Guard
When the phonetically-normalized trigger phrase (or alias) is shorter than 4 characters, the comparison requires exact equality (score 100 on equality, 0 otherwise), regardless of algorithm.
- *Why:* On a 2-character phrase like "si" a single edit is a 50-point swing, so any threshold between 51 and 99 behaves identically to exact matching while *appearing* tunable, and thresholds ≤ 50 accept any string one edit away ("se", "ci", "sa"). The guard makes behavior explicit instead of accidentally binary.
- *Trade-off:* "si grazie" will not match a bare "si" reply phrase under the guard. This is intentional for safety; users can add common longer forms ("si grazie", "va bene") as aliases.

## Risks / Trade-offs

- **[Risk]** Pure-Python Levenshtein distance might be slower for very long transcripts or extremely large trigger lists.
  - *Mitigation:* The active trigger lists (especially per-wake-word trigger sub-lists) are very short (usually <20 items), and spoken transcripts are typically <10 words. At this scale, the difference in execution time between C-compiled `rapidfuzz` and pure-Python Levenshtein is under $1$ millisecond and completely unnoticeable.
