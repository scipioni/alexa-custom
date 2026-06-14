# Proposal: `sherpa-hotwords` STT Backend

**Status:** Implemented  
**Date:** 2026-06-14  
**Scope:** Stage-1 (always-on detection)

---

## Problem

The three existing stage-1 backends each leave a gap:

| Backend | False-positive risk | Full transcription | CPU (Uno Q) |
|---|---|---|---|
| Vosk grammar | High — near-miss audio forced onto nearest phrase | No — grammar-constrained | Low |
| Vosk free-vocab | Low | Yes | Medium |
| `sherpa-onnx` KeywordSpotter | Very low | No — detect only | Low |
| `sherpa-onnx` free-vocab | Low | Yes | High |

**KeywordSpotter** is the current recommended always-on path for the Uno Q.  It rejects background speech by construction, but it only reports the detected keyword — not the full utterance.  This means single-breath "wake + command" detection requires a separate mechanism (`kws_one_breath`, extra compound keywords), and direct triggers need their phrases tokenized and registered individually.

**What is missing:** a backend that combines low false-positive risk with full ASR output, at CPU cost comparable to the free-vocab Vosk path.

---

## Proposed Solution

Add a `sherpa-hotwords` backend that runs the same `OnlineRecognizer.from_transducer` model as `sherpa-onnx` but with contextual biasing enabled via the native `hotwords_file` / `hotwords_score` parameters.

Sherpa-ONNX's contextual biasing works at the beam-search level: it dynamically adjusts decoding scores to favour paths that pass through the registered phrases.  Audio that does not resemble any hotword is **not forced** onto the nearest phrase — it is transcribed literally and subsequently rejected by the fuzzy matcher.  This is the key difference from Vosk grammar mode, where unrelated audio is forced onto the nearest token sequence.

The hotwords list is built automatically at startup from the live config — no external file is needed:

- All wake word strings and their aliases  
- All direct-trigger phrases and their aliases (`wake_words: []`)  
- Optionally: all global trigger phrases (one-breath mode)

---

## Implementation Plan

### 1. `stt_backends.py` — extend `SherpaOnnxSTT`

Add optional constructor parameters:

```python
class SherpaOnnxSTT(STTBackend):
    def __init__(
        self,
        model_dir: str = _SHERPA_MODEL_PATH,
        hotwords: list[str] | None = None,
        hotwords_score: float = 1.5,
    ) -> None:
```

When `hotwords` is not empty:
1. Write phrases to a `NamedTemporaryFile` (one phrase per line, plain text — Sherpa tokenizes internally).
2. Pass `hotwords_file=tmp.name` and `hotwords_score=hotwords_score` to `from_transducer`.
3. Delete the temp file after the recognizer is constructed (`tmp.unlink()`).

No change to `accept_waveform`, `text`, `partial_text`, `reset`, or `finalize`.

### 2. `get_stt_backend` — new branch

```python
if cfg.backend == "sherpa-hotwords":
    model_path = cfg.model_path or _SHERPA_MODEL_PATH
    return SherpaOnnxSTT(
        model_path,
        hotwords=keywords or [],
        hotwords_score=cfg.hotwords_score,
    )
```

`keywords` is already the parameter used by the KWS path — it is populated by `start_stt_thread` with wake words + direct trigger phrases.

### 3. `config.py` — `STTStage1Config`

Add one field:

```python
hotwords_score: float = 1.5   # contextual bias weight for sherpa-hotwords
```

`keywords_score` and `keywords_threshold` already exist for `KeywordSpotter` and are unrelated.

### 4. `stt.py` — `start_stt_thread`

The `_kws_keywords` list (lines 276–288) is already built correctly for the KWS path and covers wake words + direct triggers + one-breath phrases.  The `sherpa-hotwords` branch in `get_stt_backend` reuses it directly — **no change required** in `start_stt_thread`.

The hot-reload path (lines 330–343) also reuses `keywords`, but currently omits direct triggers on reload.  This is an existing bug in the KWS reload path; it should be fixed alongside this change.

### 5. `conf.example/config.yaml` and `docs/sherpa_onnx.md`

Add a `sherpa-hotwords` configuration example and a comparison row in the backend table.

---

## Configuration Example

```yaml
stt:
  stage1:
    backend: sherpa-hotwords
    model_path: models/it/kroko_128l   # same model as sherpa-onnx
    hotwords_score: 1.5                # 1.0–2.0; raise if wake word is missed
    vad_silence_ms: 900
    rms_threshold: 0.02
    min_speech_ms: 200
```

`hotwords_score` tuning:
- `1.0` — minimal bias, near free-vocab behaviour
- `1.5` — recommended starting point (Sherpa default)
- `2.0` — maximum bias; raises recall but may produce false transcriptions on near-misses

---

## Compared to Existing Backends

| Property | KeywordSpotter | sherpa-hotwords | Vosk free-vocab |
|---|---|---|---|
| Full transcription | No | Yes | Yes |
| False-positive rejection | Best (detect-only) | Very good (biased beam) | Good |
| One-breath wake+cmd | Requires compound keywords | Native (full ASR) | Native |
| Direct triggers in stage-1 | Requires tokenized phrase | Plain text, auto-built | n/a (grammar/free) |
| CPU (Uno Q, always-on) | Low (~2 threads) | Medium (~2–4 threads) | Medium |
| Manual tokenization | Yes | No | n/a |

---

## Resolved Design Questions

1. **Hotwords file format** — raw normalized text (one phrase per line), NOT pre-tokenized tokens.  `modeling_unit="bpe"` + a generated `bpe.vocab` temp file are passed to `from_transducer` so Sherpa's internal `ssentencepiece` handles tokenization.  The pre-tokenized approach was tried first but fails: `EncodeHotwords` with `modeling_unit="cjkchar"` (the default) applies `SplitUtf8` + `MergeCharactersIntoWords` to each space-delimited token — this splits off the `▁` prefix and re-merges the remaining ASCII letters into strings like `"tempo"` or `"far"` that are not in the symbol table, causing silent "Cannot find ID for token" failures.  The `bpe.vocab` is generated at startup from `tokens.txt` using quadratic token-length scores (`score = len(token)²`), which gives greedy longest-match behaviour consistent with the model's actual BPE decoding.

2. **`decoding_method`** — `hotwords_file` requires `modified_beam_search`; `greedy_search` silently ignores hotwords.  The implementation switches automatically when hotwords are provided.

3. **`modeling_unit`** — must be `"bpe"` (not the default `"cjkchar"`).  A synthetic `bpe.vocab` temp file is generated from `tokens.txt` at backend construction time and deleted on garbage collection.

## Open Questions

1. **`num_threads`**: currently hardcoded to `4` in `SherpaOnnxSTT`.  Should become a config field (`stt.stage1.num_threads`) shared by both sherpa backends to allow CPU tuning on the Uno Q.

---

## Risks

- **Hotword bias bleeds into non-trigger utterances**: with high `hotwords_score`, a phrase acoustically close to a trigger may be transcribed as the trigger even though the user said something else.  Mitigated by keeping the score at or below `1.5` and relying on the fuzzy matcher as the final gate.
- **`hotwords_file` format uncertainty** (see open question 3): if the format turns out to require pre-tokenized input, the implementation increases in complexity but is already solved by the `_tokenize_keyword` function used by `SherpaKeywordSpotter`.
