## Context

Stage-1 wake-word detection uses Vosk with a grammar restricted to the configured wake-word phrases. The small vocabulary forces Vosk to map any phonetically plausible audio onto one of the grammar phrases — making false positives nearly unavoidable for common Italian words like "aiuto" or "attenzione" when a TV is playing in the background.

The change adds confuser phrases to the grammar vocabulary. Vosk can now output them (correct acoustic match) without triggering the assistant (not in alias map).

Current pipeline:
```
parec → audio chunks → VoskSTT (grammar: ["aiuto aiuto", "aiutami"])
                      → AcceptWaveform → alias_map.get(text) → trigger or reset
```

Target pipeline:
```
parec → audio chunks → VoskSTT (grammar: ["aiuto aiuto", "aiutami", "aiuto", ...confusers])
                      → AcceptWaveform → confuser_set check (reject) → alias_map.get(text) → trigger or reset
```

## Goals / Non-Goals

**Goals:**
- Automatically derive confusers from multi-word wake phrases (sub-phrase decomposition)
- Automatically derive confusers from phonetically similar Italian words via espeak-ng IPA distance
- Allow manual confuser list per wake-word group for domain-specific terms
- `auto_confusers: false` disables all automatic computation (sub-phrase + phonetic); manual list still applies
- Zero new runtime dependencies (espeak-ng already installed for piper-tts)
- Confuser computation runs once at config load, not in the hot audio path

**Non-Goals:**
- Replacing the confirmation-step safety net (that stays as-is)
- Solving false positives in the sherpa-onnx single-stage path (that path uses fuzzy matching, not grammar)
- Supporting confusers for stage-2 recognition
- Online/adaptive learning of confusers from observed false positives

## Decisions

### Decision 1: `auto_confusers` as master switch (default `true`)

A single `auto_confusers: false` flag under `stt.stage1` disables both sub-phrase decomposition and phonetic distance computation. The manual `confusers` list per wake-word group is always honoured regardless of this flag. Setting `auto_confusers: false` restores the pre-feature grammar behaviour exactly.

**Rationale**: gives operators a clean escape hatch without requiring them to zero out individual thresholds or understand the internals.

---

### Decision 2: Sub-phrase decomposition as primary confuser source

Multi-word wake phrases like `"aiuto aiuto"` produce their component words (`"aiuto"`) as automatic confusers. This is the most impactful mechanism for emergency-style wake words.

**Implementation**: split each alias and wake word on whitespace; any token that does not itself appear as a standalone alias/wake phrase is added to the confuser set.

**Alternative considered**: require users to list confusers manually. Rejected — for "aiuto aiuto" the user would inevitably forget to add "aiuto" as confuser, reintroducing the core problem.

---

### Decision 2: espeak-ng for IPA phoneme distance (no new dependencies)

`espeak-ng --ipa -v it -q <word>` is available on both dev and target (installed alongside piper-tts). It converts Italian words to IPA strings. A simple Levenshtein distance on the IPA string finds phonetically close words in a bundled corpus.

**Alternative considered**: `phonemizer` Python library. Rejected — requires an extra pip dependency and is a wrapper around espeak-ng anyway.

**Alternative considered**: `jellyfish` (Soundex, Metaphone). Rejected — algorithms are English-optimised; IPA distance is language-neutral and more accurate for Italian.

---

### Decision 3: Bundled Italian frequency corpus (~1500 words)

A small static word list (top-frequency Italian lemmas + common proper nouns + tech terms: Arduino, Alexa, Raspberry, Google, etc.) is bundled in `alexa_custom/data/it_corpus.txt`. Phoneme distances are computed at config load time against this list.

**Cap**: `max_confusers` (default 30) prevents grammar bloat. Words are ranked by ascending IPA distance; closest ones fill the cap first.

**Alternative considered**: full Italian dictionary (~150k words). Rejected — phoneme computation for 150k words at startup is ~10s; the 1500-word corpus takes ~100ms.

---

### Decision 4: Confuser computation at config load, cached until config changes

`_build_confusers()` is called inside `_build_alias_map()` (already called on every config reload). Results are returned alongside the alias map and passed into `_grammar_json()`. No separate caching layer needed — config reload is already a low-frequency event (hot-reload every 4s only if file changed).

---

### Decision 5: Confuser rejection before alias map lookup

After `AcceptWaveform` returns a result, the text is checked against a `confuser_set` before alias map lookup:

```python
if norm_text in confuser_set:
    stage1.Reset()
    continue   # silent reject, no logging at INFO level
```

This is a separate guard (not merged into alias map lookup) to keep the intent explicit and testable.

---

### Decision 6: espeak-ng called via subprocess (not Python bindings)

`espeak-ng` is invoked as a subprocess with `--ipa -v it -q`. This matches how piper-tts uses it internally. No Python bindings (`py-espeak-ng`) are needed.

Corpus phoneme lookup is done once at startup: all 1500 words are phonemized in a single `espeak-ng` batch call (`--ipa -v it -q -f wordlist.txt`) to avoid per-word subprocess overhead.

## Risks / Trade-offs

- **Grammar size limit**: Vosk grammars degrade in quality above ~50–100 phrases. The `max_confusers` cap (default 30) plus wake phrases stays well within this.  
  → Mitigation: cap is configurable; log a warning if total grammar size exceeds 50 phrases.

- **espeak-ng not installed on target**: Unlikely (piper-tts depends on it), but possible in a minimal deployment.  
  → Mitigation: if `espeak-ng` subprocess fails, log a warning and skip phonetic confusers; sub-phrase confusers still apply.

- **IPA distance misses high-distance confusers** (e.g. "arduino" vs "galileo" at dist=6): Phonetic distance alone does not capture all cases that Vosk's acoustic model confuses.  
  → Mitigation: manual `confusers` list in config for known problematic words.

- **Sub-phrase confusers conflict with intended aliases**: If a user configures `word: "aiuto"` (single word) alongside `word: "aiuto aiuto"`, "aiuto" as a sub-phrase confuser of the latter would shadow the former.  
  → Mitigation: sub-phrase decomposition skips tokens that already appear as a standalone wake word or alias in any group.

## Migration Plan

1. Deploy updated `config.py` and `stt.py` — fully backward-compatible (new fields optional).
2. Update `config.yaml` to use multi-word emergency phrases (`"aiuto aiuto"`, `"attenzione emergenza"`).
3. Restart daemon — confusers computed at first config load, logged at DEBUG level.
4. No rollback risk: removing `confusers` fields and reverting to single-word wake phrases restores previous behaviour exactly.

## Open Questions

- **Corpus curation**: should tech terms (Arduino, Raspberry, Alexa…) be in the bundled corpus or in a separate optional file? Current plan: include ~50 common tech/IoT terms in the main corpus.
- **Threshold default**: `confuser_distance: 3` catches words at dist ≤ 3. Is this too conservative for "galileo" use cases? May need a per-group override in the future.
