## 1. Config layer

- [x] 1.1 Add `auto_confusers: bool = True` field to `STTStage1Config` in `config.py`
- [x] 1.2 Add `confuser_distance: int = 3` field to `STTStage1Config` in `config.py`
- [x] 1.3 Add `max_confusers: int = 30` field to `STTStage1Config` in `config.py`
- [x] 1.4 Add `confusers: list[str]` field (default empty) to `WakeWordGroup` in `config.py`
- [x] 1.5 Parse new fields in `_parse_stt_stage1_config()` and `_parse_wake_words()`

## 2. Confuser computation

- [x] 2.1 Implement `_subphrase_confusers(groups)` — splits multi-word wake phrases/aliases into tokens, returns tokens that are not themselves standalone wake words or aliases
- [x] 2.2 Implement `_phonetic_confusers(groups, distance, max_count)` — batch-calls `espeak-ng --ipa -v it -q` on bundled corpus + wake words, computes Levenshtein distance on IPA strings, returns closest matches up to cap; gracefully skips if espeak-ng not found
- [x] 2.3 Bundle Italian frequency corpus at `alexa_custom/data/it_corpus.txt` (~1500 common words + ~50 tech/IoT terms: Arduino, Alexa, Raspberry, Google, Siri, etc.)
- [x] 2.4 Implement `_build_confuser_set(groups, stage1_config)` — combines sub-phrase, phonetic, and manual confusers; logs at DEBUG with source breakdown and total count
- [x] 2.5 Wire `_build_confuser_set()` into the two-stage init path (called alongside `_build_alias_map()`) and return the set for use in the recognition loop

## 3. Grammar and recognition loop

- [x] 3.1 Update `_grammar_json()` to accept an optional `confuser_set` and include confuser phrases in the vocabulary alongside wake-word phrases
- [x] 3.2 Add confuser-reject guard in the Vosk two-stage recognition loop: after `AcceptWaveform` returns a result, check `norm_text in confuser_set` → reset and continue before alias map lookup
- [x] 3.3 Recompute confuser set and rebuild grammar on hot-reload (config change triggers re-init of stage-1 grammar as it already does; ensure confusers flow through)

## 4. Tests

- [x] 4.1 Unit test `_subphrase_confusers`: "aiuto aiuto" → {"aiuto"}; single-word wake word → empty; token that is itself a wake word → not included
- [x] 4.2 Unit test `_build_confuser_set` with `auto_confusers=False`: returns only manual confusers
- [x] 4.3 Unit test confuser-reject guard: mock Vosk result matching confuser → no trigger; mock result matching wake word → trigger

## 5. Config example and documentation

- [x] 5.1 Update `config.yaml.example` with commented `auto_confusers`, `confuser_distance`, `max_confusers` fields under `stt.stage1`
- [x] 5.2 Add commented `confusers` list example under a wake-word group in `config.yaml.example`, with a note on multi-word emergency phrases
