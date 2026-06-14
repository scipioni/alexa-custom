# sherpa-onnx STT Backend

alexa-custom supports **sherpa-onnx** as an alternative speech-to-text backend to Vosk. sherpa-onnx streaming models are open-vocabulary (no grammar constraints), offering potentially better command accuracy. For stage-1 wake-word detection the optional **KeywordSpotter** mode uses the same model files but with a keyword-boosted decoder — lower CPU, no false transcriptions. The **sherpa-hotwords** mode combines full ASR with contextual biasing: beam search is nudged toward registered phrases while background audio is transcribed literally and rejected by the fuzzy matcher.

---

## Compared to Vosk

| Feature | Vosk | sherpa-onnx (OnlineRecognizer) | sherpa-onnx (KeywordSpotter) | sherpa-hotwords |
|---------|------|-------------------------------|------------------------------|-----------------|
| Model | Kaldi/grammar | Streaming transducer/CTC | Streaming transducer | Streaming transducer |
| Vocabulary | Grammar-constrained | Open-vocabulary | Keyword-only | Open-vocabulary + biased |
| Stage | 1 or 2 | 1 or 2 | Stage 1 only | Stage 1 |
| CPU usage | Lower | Higher | Lower | Medium |
| Wake word accuracy | Grammar-exact | Fuzzy match | Keyword-boosted | Biased beam + fuzzy match |
| Full transcription | No (grammar) | Yes | No | Yes |
| False-positive rejection | Poor–medium | Good | Best | Very good |

For the target hardware (Arduino Uno Q, Snapdragon 801, CPU-only), **Vosk remains the default** for stage-1 due to its lower footprint. `keyword_spotter: true` is the recommended sherpa-onnx mode for always-on wake detection on that board.

---

## Rejecting background speech / false positives

This is the single most important reason to prefer the **KeywordSpotter** over Vosk grammar mode for stage-1.

**Why Vosk grammar mode false-fires on TV / background chatter:** in grammar mode (`stage1.vosk_grammar: true`) the decoder is constrained to the wake-word vocabulary. The grammar built by `_phrases_to_grammar` (`stt_backends.py:359`) *does* append the `[unk]` sink token — the canonical "none of the above" escape hatch — so clearly-unrelated audio can decode to `[unk]` instead of being forced onto a phrase. But `[unk]` is a single, flat-weighted catch-all: for audio that is *acoustically close* to a wake word (a TV, a conversation in the room), the decoder still scores the real phrase higher than the generic `[unk]` and picks it, reporting high confidence. `[unk]` rejects clearly-unrelated speech but not near-misses — which is the false-positive class most often seen.

Because of this, the grammar-mode defense must be layered rather than relying on `[unk]` alone:

- `[unk]` in the grammar (already present) — rejects clearly-unrelated audio
- `confidence_mode: min` plus a higher `confidence` floor — catches the near-miss that `[unk]` lets through, since a forced match scores poorly on at least one token
- free-vocabulary or the KeywordSpotter — removes the forced-choice pressure entirely (preferred when CPU allows)

**Why the KeywordSpotter does not:** it is a streaming keyword detector, not a recogniser. Audio that is not a configured keyword simply produces no result — non-keyword speech is rejected by construction. This solves the false-positive class *and* keeps continuous CPU low, which is why it is the recommended always-on stage-1 on the Uno Q.

The detection-score floor is **`keywords_threshold`** (default `0.25`). Raising it in `0.05` steps is the primary knob for suppressing false fires; watch the web dashboard while tuning, and back off if real wake words start being missed.

### Decoy phrases — staying in Vosk grammar mode

If you must stay in Vosk grammar mode (e.g. to avoid running a sherpa encoder continuously) you can absorb known false-positive phrases with **decoy triggers** — a trigger whose phrase is something the TV/room actually says, with empty actions:

```yaml
triggers:
  - phrase: "telegiornale"   # something the background audio produces
    actions: []              # matches the grammar, dispatches nothing
```

All trigger phrases are added to the stage-1 grammar (`_grammar_json_all`), so the decoy gives the decoder a well-scoring alternative to land on instead of the wake word; because the decoy text contains no wake word, `_extract_wake_command` returns no match and nothing fires.

**Caveat:** this is whack-a-mole — it only catches phrases you have already observed and must be maintained by hand. Free-vocabulary (`vosk_grammar: false`) or the KeywordSpotter both reject unrelated speech *generically* with no decoy list to maintain, and are preferred whenever CPU allows.

---

## Supported Model Architectures

Model type is **auto-detected** from the files present in the model directory:

| Files present | Architecture | Factory used |
|---------------|-------------|--------------|
| `joiner.onnx` or `joiner.int8.onnx` | Transducer (Zipformer, Conformer) | `from_transducer()` |
| `model.onnx` only | Zipformer2 CTC | `from_zipformer2_ctc()` |
| `encoder.onnx` + `decoder.onnx` only | Paraformer | `from_paraformer()` |

---

## Model Download

### Automatic

```bash
alexa-setup --sherpa-onnx
```

Downloads the **kroko_128l** Italian Zipformer transducer model (~148 MB) to `models/it/kroko_128l/`:

```
models/it/kroko_128l/
├── tokens.txt           # BPE vocabulary (878 tokens)
├── encoder.int8.onnx    # ~147 MB
├── decoder.int8.onnx    # ~593 KB
└── joiner.int8.onnx     # ~330 KB
```

### Manual

```bash
BASE=https://huggingface.co/hudaiapa88/sherpa-stt-onnx/resolve/main/it/kroko_128l
mkdir -p models/it/kroko_128l
for f in encoder.int8.onnx decoder.int8.onnx joiner.int8.onnx tokens.txt; do
  curl -L -o models/it/kroko_128l/$f $BASE/$f
done
```

---

## Configuration

### Stage-2 command recognition (open-vocabulary)

Use sherpa-onnx for the command window after wake detection:

```yaml
stt:
  stage2:
    backend: sherpa-onnx
    model_path: models/it/kroko_128l
```

### Stage-1 wake detection — KeywordSpotter mode (recommended for Uno Q)

Uses the same model files as stage-2 but with keyword-boosted decoding. Keywords are auto-generated from `wake_words` at startup using the model's `tokens.txt` — no extra file needed.

```yaml
stt:
  stage1:
    backend: sherpa-onnx
    model_path: models/it/kroko_128l
    keyword_spotter: true
    keywords_score: 1.0       # boost weight — raise if wake word is missed
    keywords_threshold: 0.25  # fire threshold — raise to reduce false positives
```

### Stage-1 — sherpa-hotwords (biased ASR, recommended for false-positive reduction)

Uses the same kroko model as `sherpa-onnx` but enables contextual biasing via `modified_beam_search`. Wake words, their aliases, and all direct-trigger phrases are registered as hotwords at startup — no extra config file needed.

```yaml
stt:
  stage1:
    backend: sherpa-hotwords
    model_path: models/it/kroko_128l
    hotwords_score: 1.5    # 1.0–2.0; raise if wake word is missed, lower to reduce false fires
    vad_silence_ms: 900
    rms_threshold: 0.02
    min_speech_ms: 200
```

`hotwords_score` tuning guide:
- `1.0` — minimal bias, near-identical to free-vocab `sherpa-onnx`
- `1.5` — recommended starting point
- `2.0` — maximum; maximises recall at the cost of occasional near-miss false fires

**Implementation notes**: the hotwords file contains raw normalized Italian text (one phrase per line). At startup the backend generates a temporary `bpe.vocab` file from `tokens.txt` using quadratic token-length scores, then calls `from_transducer` with `modeling_unit="bpe"` so Sherpa's ssentencepiece library tokenizes each phrase word-by-word with Viterbi decoding. `decoding_method` is automatically set to `modified_beam_search` when hotwords are present. Both temp files are deleted when the backend is garbage-collected.

---

### Stage-1 — open-vocabulary mode (higher CPU)

Runs full ASR continuously and fuzzy-matches the transcript against wake words. Useful if you want partial transcription visible in the web dashboard during stage-1.

```yaml
stt:
  stage1:
    backend: sherpa-onnx
    model_path: models/it/kroko_128l
    vad_silence_ms: 500
    rms_threshold: 0.02
    min_speech_ms: 200
```

### Full example (both stages on Uno Q)

```yaml
stt:
  stage1:
    backend: sherpa-onnx
    model_path: models/it/kroko_128l
    keyword_spotter: true
    keywords_score: 1.0
    keywords_threshold: 0.25
  stage2:
    backend: sherpa-onnx
    model_path: models/it/kroko_128l
  vad_silence_ms: 700
```

### Environment variable override

`SHERPA_ONNX_PATH` sets the default model path when `model_path` is not specified in config:

```bash
SHERPA_ONNX_PATH=models/it/kroko_128l alexa-client
```

---

## Tuning on Hardware

After deploying to the Uno Q, check the logs:

```
Stage1 KWS hit: 'galileo'       ← KeywordSpotter fired correctly
Stage1 KWS hit but keyword ...  ← fired but alias-map lookup failed (check wake_words config)
```

If the wake word is missed too often: raise `keywords_score` (e.g. `1.5`) or lower `keywords_threshold` (e.g. `0.15`).

If false positives are too frequent: raise `keywords_threshold` (e.g. `0.4`).

---

## Troubleshooting

### Model not found

```
RuntimeError: sherpa-onnx model not found at 'models/sherpa-onnx'
```

Run `alexa-setup --sherpa-onnx` or set `model_path` in `stt.stage1` / `stt.stage2` to the correct directory.

### KeywordSpotter produces empty keyword line

```
WARNING KWS: keyword 'xyz' produced empty token sequence — skipped
```

The wake word contains characters outside the model's BPE vocabulary. Use simpler Italian words or check `tokens.txt`.

### High CPU on Uno Q

**Thread counts are currently hardcoded** in `stt_backends.py`: the KeywordSpotter runs at `num_threads=2`, the full `OnlineRecognizer` (open-vocab) at `num_threads=4`. The full recogniser will use all four cores while it runs — acceptable for stage-2 (brief, post-wake) but heavy for always-on stage-1. The KeywordSpotter at 2 threads is the conservative continuous path; dropping it to 1 thread is the most impactful continuous-CPU lever, but requires making `num_threads` config-driven first.

**Hybrid fallback** — if the kroko encoder (~147 MB int8) is too heavy to run continuously, keep sherpa-onnx only for stage-2 and use Vosk for the always-on stage-1. Prefer **free-vocabulary** Vosk for stage-1 (`vosk_grammar: false`) over grammar mode — it is slightly heavier than grammar mode but rejects background/TV speech generically (see *Rejecting background speech* above), whereas grammar mode is the configuration most prone to false fires:

```yaml
stt:
  stage1:
    backend: vosk
    vosk_grammar: false   # generically rejects unrelated speech; grammar mode false-fires
  stage2:
    backend: sherpa-onnx
    model_path: models/it/kroko_128l
```
