# Proposal: Optimize VU Meters

## Summary
Replace external `pw-record` subprocesses with direct audio level calculation from the LiveKit audio stream. This improves efficiency and accuracy of the VU meters in the TUI.

## Motivation
The current TUI spawns two `pw-record` processes to monitor microphone and speaker levels. This is resource-intensive for headless systems and relies on external PipeWire tools that might not be correctly configured or available. Direct tapping into the LiveKit stream is more robust and efficient.

## Scope
- Modify `alexa_custom/client.py` to calculate peak levels for local and remote audio tracks.
- Update the event bridging to pass volume data to the TUI.
- Refactor `alexa_custom/tui.py` to remove `LevelMonitor` and listen for volume events.
- Ensure level updates are throttled (e.g., 10Hz) to prevent CPU spikes.

## Capabilities
- **audio-level-monitoring**: Real-time monitoring of microphone and speaker audio levels using direct stream tapping.

## Out of Scope
- Changing the visual style of the VU meters.
- Adding per-participant VU meters (staying with global Mic/Spk for now).
- Modifying core audio hardware interaction.
