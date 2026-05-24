# sherpa-onnx STT Backend

alexa-custom supports **sherpa-onnx** as an alternative speech-to-text backend to Vosk. sherpa-onnx uses streaming models which are open-vocabulary (no grammar constraints), potentially offering better accuracy for command recognition at the cost of higher CPU usage.

---

## Compared to Vosk

| Feature | Vosk | sherpa-onnx |
|---------|------|-------------|
| Model | Kaldi-based | Streaming transducer/Paraformer |
| Vocabulary | Grammar-constrained | Open-vocabulary |
| CPU usage | Lower | Higher |
| Accuracy | Good | Potentially better |
| Wake word detection | Grammar-mode | Open transcription |

For the constrained target hardware (Arduino Uno Q as USB audio gadget), **Vosk remains the default** for wake word detection due to its lower CPU footprint.

---

## Supported Models

The sherpa-onnx backend supports both **transducer** models (encoder/decoder/joiner) and **Paraformer** models (encoder/decoder).

A working Italian model is **kroko_128l** — a streaming Zipformer transducer model converted to ONNX.

### Model Files Required

**For transducer models** (encoder/decoder/joiner):
```
models/sherpa-onnx/
├── tokens.txt          # Vocabulary
├── encoder.int8.onnx  # Encoder (int8 optimized)
├── decoder.int8.onnx  # Decoder (int8 optimized)
└── joiner.int8.onnx   # Joiner (int8 optimized)
```

**For Paraformer models** (encoder/decoder):
```
models/sherpa-onnx/
├── tokens.txt      # Vocabulary
├── encoder.onnx    # Encoder model
└── decoder.onnx    # Decoder model
```

---

## Downloading the Model

### Automatic Download

```bash
python -m alexa_custom.setup --sherpa-onnx
```

This downloads the kroko_128l Italian model to `models/it/kroko_128l/` via HuggingFace.

### Manual Download

Download from HuggingFace using the `hf` CLI:

```bash
hf download hudaiapa88/sherpa-stt-onnx \
  --local-dir ./models \
  --include "it/kroko_128l/*"
```

Or place the model files directly in `models/it/kroko_128l/`.

---

## Configuration

### config.yaml

```yaml
stt:
  backend: sherpa-onnx
```

Or use the legacy single-key form:

```yaml
stt_backend: sherpa-onnx
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SHERPA_ONNX_PATH` | `models/sherpa-onnx` | Path to the sherpa-onnx model directory |

Point to your model location:

```bash
SHERPA_ONNX_PATH=models/it/kroko_128l alexa-client
```

---

## Switching Backends

### At Runtime

Edit `config.yaml` and set `stt.backend: vosk` or `stt.backend: sherpa-onnx`. The change takes effect on next hot-reload (approx. 4 seconds).

### Via CLI

```bash
# Use Vosk (default)
alexa-client

# Use sherpa-onnx
SHERPA_ONNX_PATH=models/it/kroko_128l alexa-client
```

---

## Troubleshooting

### Model Not Found

```
RuntimeError: sherpa-onnx model not found at 'models/sherpa-onnx'. Run 'alexa-setup --sherpa-onnx' to download it.
```

Ensure your model is in the path specified by `SHERPA_ONNX_PATH`:

```bash
ls models/it/kroko_128l/
# Should show: tokens.txt, encoder.int8.onnx, decoder.int8.onnx, joiner.int8.onnx
```

### High CPU Usage

If sherpa-onnx causes high CPU usage on your device, switch back to Vosk:

```yaml
stt:
  backend: vosk
```

### Audio Quality Issues

sherpa-onnx expects 16kHz mono PCM audio (same as Vosk). If you see degraded accuracy, check that your audio source is delivering at the correct sample rate.
