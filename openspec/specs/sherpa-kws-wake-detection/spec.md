# Capability: sherpa-kws-wake-detection

## Purpose

Wake-word detection using `sherpa_onnx.KeywordSpotter` as the stage-1 backend. When enabled, the spotter fires directly on keyword detection without relying on the energy VAD, reducing false wake events and latency on target hardware.

> **REMOVED**: All requirements in this capability have been removed. The dedicated KWS cheap-gate stage is replaced by the single always-on transcription model (see `single-model-stt`). Wake detection now happens by matching the single transcription model's output against the configured wake words. To use sherpa for recognition, set `stt.backend: sherpa-onnx`.
