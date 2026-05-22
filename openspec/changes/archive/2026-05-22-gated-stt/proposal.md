# Proposal: Gated STT during calls

## Problem
Currently, the Speech-to-Text (STT) engine using Vosk remains fully active even when a LiveKit call is in progress. This leads to several issues:
1. **CPU Overhead**: Running Vosk inference while simultaneously handling AEC/NS and audio streaming for a call is taxing on constrained hardware.
2. **False Triggers**: Audio from the speaker during a call can be misidentified as a wake word or command, even with Acoustic Echo Cancellation.
3. **Redundant Actions**: Users don't typically want to trigger secondary actions (like sending a Telegram message) while they are actively talking in a room.

## Proposed Solution
Introduce a "Gating" mechanism in the STT loop that respects the `livekit_connected_flag`.

### Key Features
- **Audio Discarding**: When a call is active, audio chunks are read from the pipe (to prevent buffer bloat) but are immediately discarded instead of being processed by Vosk.
- **Safety Cooldown**: After a call ends, a 1.0-second cooldown is enforced before STT inference resumes. This prevents hang-up tones or the final words of a call from triggering the wake word.
- **Visual Feedback**: The TUI will display a "STT Gated" state to inform the user that the engine is temporarily paused.
- **Automatic Resume**: STT automatically returns to the "Listening" state once the call ends and the cooldown expires.

## Scope
- `alexa_custom/stt.py`: Logic to check the flag, discard audio, and manage the cooldown.
- `alexa_custom/tui.py`: UI updates to reflect the gated state.

## Success Criteria
- STT does not trigger any actions while `livekit_connected_flag` is set.
- CPU usage drops significantly during active calls.
- STT resumes reliably within ~1 second of a call ending.
- The TUI clearly shows when the engine is gated.
