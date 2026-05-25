---
name: test-stt-e2e
description: Run an end-to-end STT test that simulates a real voice conversation with alexa-custom. Synthesises Italian speech using piper TTS, feeds it through the configured STT backend (Vosk or sherpa-onnx), and reports recognition results. Use when you want to verify STT is working without a real microphone.
license: MIT
metadata:
  author: stefano.scipioni@csgalileo.net
  version: "1.0"
---

Run an end-to-end STT test for alexa-custom. The test synthesises Italian speech with piper and feeds it through the STT backend without any real microphone.

## Steps

1. **Check prerequisites** — verify that piper, ffmpeg, and the STT model directories exist.

2. **Run the e2e test suite**:
   ```
   task test-stt-e2e
   ```
   This runs `tests/test_stt_e2e.py` which:
   - Synthesises test phrases ("ehi galileo", "chiama stefano", "ehi galileo chiama stefano") using piper with the `it_IT-paola-medium` voice
   - Resamples from 22050 Hz to 16 kHz mono s16le via ffmpeg
   - Feeds PCM in 4096-byte chunks through the STT backend
   - Asserts that recognised text contains the expected Italian words

3. **Report results** — show which tests passed/failed and what text was actually recognised. If a test fails, show the recognised text verbatim so the user can see what the model produced.

4. **Diagnose failures** — if recognition fails:
   - Check that `config.yaml` has `stt:` block uncommented with correct `backend` and `model_path`
   - Check model files exist at the configured path (encoder.int8.onnx, decoder.int8.onnx, joiner.int8.onnx, tokens.txt)
   - Run `alexa-setup --sherpa-onnx` if models are missing
   - Check logs for backend initialisation errors

5. **Quick smoke test** (without pytest) — to test a single phrase interactively:
   ```python
   from alexa_custom.stt import SherpaOnnxSTT
   import subprocess, tempfile, os

   backend = SherpaOnnxSTT("models/it/kroko_128l")
   # synthesise
   with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
       wav = f.name
   subprocess.run([".venv/bin/piper", "--model", "models/piper/it_IT-paola-medium.onnx",
                   "--output_file", wav], input=b"ehi galileo", check=True)
   pcm = subprocess.run(["ffmpeg", "-y", "-i", wav, "-ar", "16000", "-ac", "1",
                         "-f", "s16le", "pipe:1"], capture_output=True, check=True).stdout
   os.unlink(wav)
   # feed
   import io
   buf = io.BytesIO(pcm)
   while chunk := buf.read(4096):
       if backend.accept_waveform(chunk):
           print("endpoint:", backend.text()); backend.reset()
   print("final:", backend.text())
   ```
