## Context

The `alexa-custom` client operates in a headless environment where audio reliability is paramount. Previous iterations required manual profile switching (e.g., to mSBC for Bluetooth) and routing setup. Additionally, the lack of voice feedback limited the assistant's usability.

## Goals / Non-Goals

**Goals:**
- Automate PipeWire profile and routing management via a proactive background watcher.
- Implement an interchangeable TTS system with local (Pico) support.
- Ensure STT recognition does not trigger on the assistant's own speech.
- Optimize audio performance for resource-constrained hardware (e.g., Bluetooth at 16kHz).

**Non-Goals:**
- Implementing cloud-based TTS backends (e.g., Google, Amazon) in this phase.
- Automating the generation of system-level WirePlumber `.conf` files.

## Decisions

- **Event-Driven Audio Monitoring**: Use a `pulsectl`-based daemon thread (`AudioWatcher`) that listens for PipeWire state changes and re-enforces desired hardware profiles and default routing.
- **Dynamic Sample Rate Selection**: Detect Bluetooth connections and automatically downsample LiveKit sessions to 16kHz to reduce CPU overhead and improve mixer stability on weak hardware.
- **Session-Local Player Lifecycle**: Create and destroy the LiveKit `AudioOutput` (player) for each call session. This ensures a fresh audio state and resolves "stuck" mixer issues observed with long-lived players.
- **Backend-Agnostic TTS**: Define a `TTSBackend` interface in `alexa_custom/tts.py`. This allows swapping Pico TTS for higher-quality local or cloud models in the future without changing the action dispatcher.
- **Explicit STT Gating**: Use `threading.Event` flags to signal when the assistant is speaking or in a call, allowing the STT pipeline to pause recognition and save CPU.

## Risks / Trade-offs

- [Risk] → **Race Conditions in PipeWire**: Switching profiles can be slow.
- [Mitigation] → Added `time.sleep(0.5)` and card refresh logic in the enforcer to allow PipeWire state to stabilize.
- [Risk] → **CPU Spikes during TTS**: Generating speech while recognition is active can cause audio drops.
- [Mitigation] → Explicitly gate (pause) the STT recognizer during TTS playback.
