# Capability: Streaming Intent Detection

## Purpose
Continuously scan Vosk partial transcripts for complete (wake + trigger) intents, firing immediately when a match is stable — bypassing the VAD silence wait and reducing response latency.

> **REMOVED**: All requirements in this capability have been removed. Partial-transcript intent firing is replaced by endpoint-gated matching in the single-model loop (see `single-model-stt` and `command-wake-gating`). One-breath "wake + command" is still supported, resolved at endpoint time by matching the finalized transcript against wake words and commands. Remove `recognition.partial_matching`, `partial_stability_ms`, and `partial_stability_reads` from config.
