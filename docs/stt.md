# STT Pipeline and Trigger Matching

alexa-custom runs a single-stage always-on speech pipeline. A single Vosk free-vocabulary model transcribes audio continuously; wake words and command triggers are matched directly against this stream.

---

## Pipeline overview

```
mic audio
   │
   ▼
always-on STT (Vosk)
   │  transcribes speech continuously (Vosk free-vocabulary)
   │
   ▼
TRIGGER MATCHING (match_trigger)
   │
   ├─ wake word matched?
   │      YES → open command window / follow-up, match command phrases
   │      NO  → check if direct trigger (wake_words: []) is matched
   │
   ▼
ACTION DISPATCH
   │
   ├─ match  → dispatch action
   ├─ no match + LLM enabled → LLM fallback
   └─ no match → error tone
```

---

## Trigger matching

Every command transcript passes through `match_trigger()`, regardless of which speaking pattern triggered it. Matching has two steps:

### 1. Word-glob patterns (definitive)

If a trigger defines `patterns`, these are tested first. A pattern match immediately selects that trigger — no scoring, no fallback to other triggers.

A pattern is a sequence of space-separated tokens:

| Token | Meaning |
|---|---|
| `accend*` | a word that *starts with* `accend` — matches accendi / accenda / accendere / … |
| `*` (standalone) | any number of intervening words, including zero |
| `luci` | a word matched **phonetically** — `luce` still passes via the similarity threshold |

Tokens are aligned in order (a fuzzy ordered-subsequence walk). Order matters; there is no "any order" operator.

```yaml
triggers:
  - phrase: "accendi le luci"        # fuzzy fallback if no pattern hits
    patterns:
      - "accend* * luci"             # accendi/accenda… + any words + luci/luce
    actions:
      - type: mqtt_publish
        params: { topic: "home/lights/on" }
```

What `"accend* * luci"` matches:

| Transcript | Result |
|---|---|
| `accendi le luci` | ✅ |
| `accendimi le luci del salotto` | ✅ |
| `accendi le luce` (STT slip) | ✅ phonetic tolerance |
| `luci accendi` | ❌ wrong order |
| `spegni le luci` | ❌ no word starts with `accend` |

### 2. Fuzzy phonetic scoring (fallback)

When no pattern matches (or none are defined), the system scores the transcript against each trigger's `phrase` and `aliases` using `italian_phonetic()` normalization and the configured `matching_algorithm`. The trigger with the highest score above `matching_threshold` wins.

Triggers without `patterns` behave exactly as before this feature existed.

---

## Speaking patterns

The wake-word detection in stage 1 supports three interaction styles. These modes work seamlessly whether `vosk_grammar` is enabled or not, because in grammar mode the system compiles both your wake words and command triggers into the allowed vocabulary. To ensure compatibility with Vosk's internal model vocabulary, all phrases in the compiled grammar are automatically normalized to lowercase and stripped of diacritics and accents (e.g., `è` -> `e`, `sì` -> `si`). This prevents vocabulary-related warnings while maintaining exact matching.

### Mode 1 — wake word → beep → command (separate utterances)

```
[user: "galileo"]  →  beep  →  [user: "che ora è"]  →  match
```

1. Stage 1 fires on the wake word alone (`inline_cmd` empty).
2. Beep plays; any audio buffered during playback is flushed.
3. Stage 2 captures the next utterance and returns the transcript.
4. `match_trigger()` runs on the transcript.

Tune `stage1.vad_silence_ms` to control how long after the wake word before stage 1 fires. Lower = snappier; too low = misses the command spoken in one breath (see mode 2).

### Mode 2 — one breath (wake word + command)

```
[user: "galileo chiama stefano"]  →  beep  →  match (stage 2 skipped)
```

1. Stage 1 fires on the full phrase; `_extract_wake_command` strips the wake word and returns the remainder as `inline_cmd`.
2. Beep plays. Stage 2 is **skipped** — `inline_cmd` goes straight to `match_trigger()`.

Fails silently if the user pauses longer than `stage1.vad_silence_ms` between wake word and command; stage 1 then fires on the wake word alone and falls back to mode 1 (the command audio is discarded). Raise `stage1.vad_silence_ms` (e.g. 900 ms) to bridge natural micro-pauses.

### Mode 3 — streaming intent (fires on partial transcript)

```
[user still speaking: "galileo chiam…"]  →  partial stable 150ms  →  beep  →  match
```

1. On every audio chunk, `_match_full_intent()` checks the Vosk partial transcript against a pre-built map of `(wake phrase + trigger phrase)` combos.
2. When the same full-intent match is stable for ≥ `partial_stability_reads` reads and ≥ `partial_stability_ms` wall-clock time, `_wake_detected` fires immediately.
3. Stage 2 is skipped.

Mode 3 uses **exact matching only** (no fuzzy, no glob patterns). If the partial never stabilises at an exact phrase, it falls through to mode 1/2. Fix by adding the mistranscribed form as an alias.

---

## Comparison

| | Mode 1 | Mode 2 | Mode 3 |
|---|---|---|---|
| Speaking pattern | Wake → pause → beep → command | Wake + command, one breath | Wake + command, one breath |
| Stage-2 capture | Yes | No | No |
| Latency after last word | `stage1.vad_silence_ms` | `stage1.vad_silence_ms` | `partial_stability_ms` (~150ms) |
| Trigger matching | patterns → fuzzy | patterns → fuzzy | exact only (intent map) |
| LLM fallback | Yes | Yes | Falls back to mode 1/2 + LLM |

---

## Direct-match triggers (no wake word)

A trigger with an explicit empty `wake_words: []` is a **direct-match trigger**: it fires from stage 1 *without* any wake word, the moment the phrase itself is recognised.

```yaml
triggers:
  - phrase: "chiama Stefano"
    wake_words: []        # direct match — fires without a wake word
    actions:
      - type: livekit_join
```

Because there is no wake word gating these, they are matched far more strictly than command triggers (§ Trigger matching) to keep ambient speech from firing them. The rule is:

- **Algorithm: `ratio`** (character-level), *not* `matching_algorithm`/`token_set_ratio`. `token_set_ratio` ignores word order and extra words, so a longer utterance that merely *contains* the trigger's words would score ~100 and mis-fire. Character-level `ratio` rejects those because the full strings differ in length.
- **Full word overlap (`min_word_overlap = 1.0`)** — every word of the trigger phrase must appear in the transcript before fuzzy scoring even runs.
- **Word-count gate** — a trigger is only a candidate when the transcript has *at least* as many words as the phrase, so a single noise token (`"e"`) can't match a multi-word trigger (`"che ora è"`).
- **Threshold** — the resulting `ratio` score must still clear `matching_threshold`.

The trade-off is deliberate: direct triggers favour precision over recall. A phrase the STT consistently mis-transcribes should be added as an `alias` on the trigger rather than loosened globally.

> One-breath note: a keyword like `"galileo chiama stefano"` is *not* treated as the direct trigger `"chiama stefano"` — the full-overlap-plus-`ratio` rule rejects it, so it correctly falls through to wake-word + inline-command handling (mode 2).

---

## Real-world examples — Italian domotic and elderly care

The word-glob patterns are particularly valuable here because elderly users rephrase the same intent naturally across calls, and Italian verb inflection means "accendi / accenda / accendere / accendimi" are all the same intent. A single pattern absorbs the variation that would otherwise require dozens of aliases.

### Home automation (domotica)

```yaml
triggers:

  # ── Lights ────────────────────────────────────────────────────────────────
  - phrase: "accendi le luci"
    patterns:
      - "accend* * luc*"          # accendi/accenda/accendere … luci/luce/lucine
      - "mett* * luc*"            # metti/mettere la luce
    actions:
      - type: mqtt_publish
        params: { topic: "home/lights/on", payload: "ON" }

  - phrase: "spegni le luci"
    patterns:
      - "spegn* * luc*"           # spegni/spegnere/spegnete … luci/luce
    actions:
      - type: mqtt_publish
        params: { topic: "home/lights/off", payload: "OFF" }

  # ── Climate ───────────────────────────────────────────────────────────────
  - phrase: "alza il riscaldamento"
    patterns:
      - "alz* * riscaldament*"    # alza/alzare/alzami il/lo riscaldamento
      - "aumenta * temperatura"   # aumenta la temperatura
      - "ho * freddo"             # ho freddo / ho molto freddo → turn up heat
    actions:
      - type: mqtt_publish
        params: { topic: "home/climate/heat", payload: "UP" }

  - phrase: "abbassa il riscaldamento"
    patterns:
      - "abbass* * riscaldament*"
      - "diminuisc* * temperatura"
      - "ho * caldo"              # ho caldo / ho troppo caldo
    actions:
      - type: mqtt_publish
        params: { topic: "home/climate/heat", payload: "DOWN" }

  # ── Shutters ──────────────────────────────────────────────────────────────
  - phrase: "alza le tapparelle"
    patterns:
      - "alz* * tapparell*"       # alza/alzare le/delle tapparelle/tapparella
      - "apr* * tapparell*"       # apri/aprire le tapparelle
    actions:
      - type: mqtt_publish
        params: { topic: "home/shutters", payload: "UP" }

  - phrase: "abbassa le tapparelle"
    patterns:
      - "abbass* * tapparell*"
      - "chud* * tapparell*"      # chiudi/chiudere → phonetic "kudi"
    actions:
      - type: mqtt_publish
        params: { topic: "home/shutters", payload: "DOWN" }

  # ── TV ────────────────────────────────────────────────────────────────────
  - phrase: "accendi la tv"
    patterns:
      - "accend* * tv"
      - "accend* * televisor*"    # televisore/televisori
      - "mett* * tv"
    actions:
      - type: mqtt_publish
        params: { topic: "home/tv", payload: "ON" }
```

### Elderly care (assistenza anziani)

These triggers prioritise **recall** — they fire even when the user's phrasing is distressed, rushed, or incomplete. The patterns are intentionally broad; the emergency ones especially must not miss.

```yaml
triggers:

  # ── Emergency — call for help ─────────────────────────────────────────────
  - phrase: "chiama il medico"
    patterns:
      - "chiam* * medico"         # chiama/chiamate/chiamami il/un medico
      - "ho * bisogno * medico"   # ho bisogno di un medico
      - "serve * medico"          # mi serve un medico
    actions:
      - type: telegram
        params:
          chat_id: "${TELEGRAM_CHAT_ID}"
          text: "⚠️ Richiesta di aiuto: chiamare il medico"
      - type: say
        params: { text: "Sto avvisando i tuoi familiari, arrivo subito." }

  - phrase: "chiama i carabinieri"
    patterns:
      - "chiam* * carabinier*"
      - "chiam* * polizia"
      - "chiam* * emergenza"
      - "chiam* * soccorso"
    actions:
      - type: telegram
        params:
          chat_id: "${TELEGRAM_CHAT_ID}"
          text: "🚨 Emergenza: richiesta aiuto urgente"

  # ── Distress — not feeling well ───────────────────────────────────────────
  - phrase: "non sto bene"
    patterns:
      - "non * bene"              # non sto bene / non mi sento bene
      - "sto * male"              # sto male / sto molto male
      - "mi * male"               # mi sento male / mi fa male
      - "son* * male"             # sono/sono rimasto male
    actions:
      - type: telegram
        params:
          chat_id: "${TELEGRAM_CHAT_ID}"
          text: "⚠️ Non si sente bene"
      - type: say
        params: { text: "Ho avvisato i tuoi familiari. Come posso aiutarti?" }

  # ── Fall ──────────────────────────────────────────────────────────────────
  - phrase: "sono caduto"
    patterns:
      - "son* cadat*"             # sono caduto/caduta
      - "son* cadut*"
      - "mi son* fat* male"       # mi sono fatto/fatta male
      - "ho * cadut*"             # ho caduto (common informal)
    actions:
      - type: telegram
        params:
          chat_id: "${TELEGRAM_CHAT_ID}"
          text: "🚨 Possibile caduta — verificare immediatamente"
      - type: say
        params: { text: "Avviso i tuoi familiari. Cerca di non muoverti." }

  # ── Call a family member ──────────────────────────────────────────────────
  - phrase: "chiama mia figlia"
    patterns:
      - "chiam* * figli*"         # chiama mia figlia/figlio/figliolo
      - "chiam* * famiglia"       # chiama la mia famiglia
      - "voglio * parlar* * figli*"
    actions:
      - type: livekit_join

  # ── Medication reminder ───────────────────────────────────────────────────
  - phrase: "ho preso le medicine"
    patterns:
      - "pres* * medicin*"        # ho preso le medicine/medicina
      - "pres* * farmac*"         # ho preso il farmaco
      - "pres* * pastiglie"
    actions:
      - type: mqtt_publish
        params: { topic: "care/medication/taken", payload: "true" }
      - type: say
        params: { text: "Perfetto, ho segnato che hai preso le medicine." }

  - phrase: "non ho preso le medicine"
    patterns:
      - "non * pres* * medicin*"
      - "dimentica* * medicin*"   # ho dimenticato le medicine
      - "medicin* * dimenticat*"
    actions:
      - type: say
        params: { text: "Ti ricordo di prendere le medicine adesso." }
      - type: mqtt_publish
        params: { topic: "care/medication/missed", payload: "true" }

  # ── Daily wellbeing check-in ──────────────────────────────────────────────
  - phrase: "sto bene grazie"
    patterns:
      - "sto * bene"              # sto bene / sto benissimo / sto abbastanza bene
      - "mi sent* * bene"         # mi sento bene
      - "tutto * bene"            # tutto bene / va tutto bene
    actions:
      - type: mqtt_publish
        params: { topic: "care/checkin/status", payload: "ok" }
      - type: say
        params: { text: "Sono contento. Buona giornata!" }
```

### Why patterns matter here

A literal alias approach requires you to enumerate: `"chiama il medico"`, `"chiamate il medico"`, `"chiamami il medico"`, `"ho bisogno del medico"`, `"mi serve un medico"` — and you still miss `"puoi chiamare il medico per me"`. The pattern `"chiam* * medico"` covers the call-verb family in one token; `"ho * bisogno * medico"` covers the need-expression in another. More importantly, Vosk on a small Italian model will sometimes return `"caduta"` for `"caduto"` — the phonetic match on `cadat*`/`cadut*` absorbs that without a separate alias.

---

## Configuration reference

```yaml
stt:
  backend: vosk            # speech-to-text backend (must be vosk)
  vad_silence_ms: 900      # idle ms before command window closes
  rms_threshold: 0.02      # minimum RMS energy level to count as speech
  adaptive_rms: true       # dynamically adjust threshold based on room noise floor
  adaptive_rms_margin: 0.01
  min_speech_ms: 200       # minimum sustained speech before silence timer starts
  wake_match_threshold: 0.5 # similarity threshold (0.0 to 1.0) to match a wake word

recognition:
  command_timeout: 2.5       # inactivity window for stage-2 (slides while user speaks)
  command_max_timeout: 8.0   # absolute cap on stage-2 capture
  matching_algorithm: token_set_ratio   # token_set_ratio | levenshtein | ratio
  matching_threshold: 70.0   # 0–100; fuzzy score cutoff
  partial_matching: true     # enable mode 3
  partial_stability_ms: 150  # ms a partial must be stable before mode 3 fires
  partial_stability_reads: 3 # consecutive matching partial reads required

wake_words:
  - word: "ehi galileo"
    # skip_unmatched_inline: false  # true = silently ignore unrecognised inline commands
```

### Key tuning knobs

| Symptom | Fix |
|---|---|
| Mode 2 keeps falling back to mode 1 | Raise `stt.vad_silence_ms` (e.g. 900–1200 ms) |
| Pipeline cuts off long commands | Raise `command_timeout` or `command_max_timeout` |
| Pipeline doesn't end promptly after command | Lower `stt.vad_silence_ms` |
| Glob pattern too permissive | Add a stronger anchor token; avoid bare single-token patterns |
| Direct trigger (`wake_words: []`) won't fire | Add the mis-transcribed form as an `alias` |
| Direct trigger fires on unrelated speech | It shouldn't — direct matching is strict (`ratio` + full overlap); check the trigger isn't a single very short word |
