# sherpa-onnx STT Backend

alexa-custom supports **sherpa-onnx** as an alternative speech-to-text backend to Vosk. sherpa-onnx uses the Paraformer model which is open-vocabulary (no grammar constraints), potentially offering better accuracy for command recognition at the cost of higher CPU usage.

---

## Compared to Vosk

| Feature | Vosk | sherpa-onnx |
|---------|------|-------------|
| Model | Kaldi-based | Streaming Paraformer |
| Vocabulary | Grammar-constrained | Open-vocabulary |
| CPU usage | Lower | Higher |
| Accuracy | Good | Potentially better |
| Wake word detection | Grammar-mode | Open transcription |

For the constrained target hardware (Arduino Uno Q as USB audio gadget), **Vosk remains the default** for wake word detection due to its lower CPU footprint.

---

## Downloading the Model

### Automatic Download

```bash
python -m alexa_custom.setup --sherpa-onnx
```

This downloads the Italian Paraformer model to `models/sherpa-onnx/`.

### Manual Download

Download from the [k2-fsa sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models) and extract to `models/sherpa-onnx/`:

```bash
mkdir -p models/sherpa-onnx
tar xf sherpa-onnx-paraformer-ita.tar.bz2 -C models/sherpa-onnx --strip-components=1
```

### Model Files Required

```
models/sherpa-onnx/
├── tokens.txt      # Vocabulary
├── encoder.onnx    # Encoder model
└── decoder.onnx    # Decoder model
```

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

---

## Switching Backends

### At Runtime

Edit `config.yaml` and set `stt.backend: vosk` or `stt.backend: sherpa-onnx`. The change takes effect on next hot-reload (approx. 4 seconds).

### Via CLI

```bash
# Use Vosk (default)
alexa-client

# Use sherpa-onnx
STT_BACKEND=sherpa-onnx alexa-client
```

---

## Troubleshooting

### Model Not Found

```
RuntimeError: sherpa-onnx model not found at 'models/sherpa-onnx'. Run 'alexa-setup --sherpa-onnx' to download it.
```

Run the setup script:
```bash
python -m alexa_custom.setup --sherpa-onnx
```

### High CPU Usage

If sherpa-onnx causes high CPU usage on your device, switch back to Vosk:

```yaml
stt:
  backend: vosk
```

### Audio Quality Issues

sherpa-onnx expects 16kHz mono PCM audio (same as Vosk). If you see degraded accuracy, check that your audio source is delivering at the correct sample rate.
