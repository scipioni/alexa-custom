#!/usr/bin/env python3
"""Italian speech-to-text on the Arduino UNO Q with sherpa-onnx (Whisper base int8)."""

import sys
import wave
import numpy as np
import sherpa_onnx

MODEL_DIR = "models/sherpa-onnx-whisper-base"

recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
    encoder=f"{MODEL_DIR}/base-encoder.int8.onnx",
    decoder=f"{MODEL_DIR}/base-decoder.int8.onnx",
    tokens=f"{MODEL_DIR}/base-tokens.txt",
    language="it",  # force Italian
    task="transcribe",
    num_threads=4,  # all four Cortex-A53 cores
)

with wave.open(sys.argv[1]) as f:
    assert f.getframerate() == 16000 and f.getnchannels() == 1, "need 16 kHz mono WAV"
    samples = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    samples = samples.astype(np.float32) / 32768.0

stream = recognizer.create_stream()
stream.accept_waveform(16000, samples)
recognizer.decode_stream(stream)
print(stream.result.text)
