## Why

The Vosk stage-1 recogniser uses a grammar restricted to configured wake-word phrases. With a small vocabulary, Vosk is forced to map any phonetically plausible audio onto one of those phrases — even unrelated speech. This is especially problematic for emergency wake words ("aiuto", "attenzione") which are common Italian words that appear frequently in normal speech and TV audio. The system needs a way to give Vosk enough acoustic contrast to reject false matches without requiring users to manually curate long lists of phonetically similar words.

## What Changes

- The stage-1 grammar is expanded with **confuser phrases** — words and sub-phrases that Vosk can now recognise and reject, rather than being forced to map them onto a wake word.
- Confusers are **computed automatically** from two sources:
  1. **Sub-phrase decomposition**: each component word of a multi-word wake phrase (e.g. `"aiuto"` from `"aiuto aiuto"`) is added as a confuser so a single utterance does not trigger.
  2. **Phonetic distance**: at config load time, common Italian words within a configurable IPA-phoneme edit distance (via `espeak-ng`, already installed) are added as confusers.
- A manual `confusers` list per wake-word group allows explicit overrides and additions (e.g. `"arduino"`, domain-specific terms).
- Confuser phrases are added to the Vosk grammar vocabulary but **not** to the alias map, so Vosk can output them without triggering the assistant.

## Capabilities

### New Capabilities

- `wake-word-confusers`: Automatic and manual confuser phrase generation that expands the Vosk stage-1 grammar so phonetically similar words and partial wake phrases are recognised and explicitly rejected rather than misidentified as wake words.

### Modified Capabilities

- `wake-word-detection`: The stage-1 grammar now includes confuser phrases alongside wake-word phrases. The recognition requirement is extended: confuser matches SHALL be silently ignored and the recogniser reset without triggering command mode.

## Impact

- **`alexa_custom/config.py`**: `WakeWordGroup` — add `confusers: list[str]` field (manual override); `STTStage1Config` — add `auto_confusers: bool` (default `true`), `confuser_distance: int` (default 3) and `max_confusers: int` (default 30) fields.
- **`alexa_custom/stt.py`**: new `_build_confusers()` function — sub-phrase decomposition + phonetic distance via `espeak-ng`; `_grammar_json()` — include computed confusers; matching logic — explicit confuser-reject guard after alias map lookup.
- **`config.yaml.example`**: add commented `confusers` example and note on multi-word emergency phrases.
- **Dependencies**: none new — `espeak-ng` is already present (used by piper-tts).
- No breaking changes; all new fields are optional with safe defaults.

## Usage example

```yaml
wake_words:
  - word: "aiuto aiuto"          # double call — emergencies only
    aliases:
      - "aiutami"
      - "mi serve aiuto"
    # "aiuto" (single) → auto-confuser via sub-phrase decomposition

  - word: "attenzione emergenza"
    aliases:
      - "attenzione aiuto"
    # "attenzione" alone → auto-confuser

stt:
  stage1:
    auto_confusers: true    # set to false to disable all automatic generation
    confuser_distance: 3    # IPA phoneme edit distance threshold
    max_confusers: 30       # grammar size cap
```
