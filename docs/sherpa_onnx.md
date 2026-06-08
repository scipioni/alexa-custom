# sherpa-onnx STT Backend

alexa-custom supports **sherpa-onnx** as an alternative speech-to-text backend to Vosk. sherpa-onnx streaming models are open-vocabulary (no grammar constraints), offering potentially better command accuracy. For stage-1 wake-word detection the optional **KeywordSpotter** mode uses the same model files but with a keyword-boosted decoder — lower CPU, no false transcriptions.

---

## Compared to Vosk

| Feature | Vosk | sherpa-onnx (OnlineRecognizer) | sherpa-onnx (KeywordSpotter) |
|---------|------|-------------------------------|------------------------------|
| Model | Kaldi/grammar | Streaming transducer/CTC | Streaming transducer |
| Vocabulary | Grammar-constrained | Open-vocabulary | Keyword-only |
| Stage | 1 or 2 | 1 or 2 | Stage 1 only |
| CPU usage | Lower | Higher | Lower (tuned for wake words) |
| Wake word accuracy | Grammar-exact | Fuzzy match | Keyword-boosted beam search |

For the target hardware (Arduino Uno Q, Snapdragon 801, CPU-only), **Vosk remains the default** for stage-1 due to its lower footprint. `keyword_spotter: true` is the recommended sherpa-onnx mode for always-on wake detection on that board.

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

Switch stage-1 to Vosk (grammar-constrained) and keep sherpa-onnx only for stage-2:

```yaml
stt:
  stage1:
    backend: vosk
  stage2:
    backend: sherpa-onnx
    model_path: models/it/kroko_128l
```
