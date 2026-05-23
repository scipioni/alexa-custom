## Why

The current `alexa-client` implementation has accumulated architectural debt, particularly around session management and action dispatch. This leads to inefficient resource usage (e.g., peak calculation overhead), tightly coupled components, and difficulty in extending the action system. These improvements address performance bottlenecks and establish a more robust, extensible foundation.

## What Changes

- **Session Management**: Extract LiveKit room and track coordination into a dedicated `LiveKitSessionManager` class.
- **Action Dispatch**: Implement an Action Registry pattern to replace the monolithic conditional block in `actions.py`.
- **Peak Calculation**: Optimize audio peak calculation to work directly with `int16` buffers, avoiding expensive memory allocation and casting to `float32`.
- **Reconnection Logic**: Implement exponential backoff for LiveKit session reconnections.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `action-dispatch`: Refactoring implementation; no requirement changes at the spec level, but internal handling is changing.
- `audio-management`: Optimizing internal calculations; no requirement changes.

## Impact

- `alexa_custom/client.py`: Significant refactoring to decouple session logic.
- `alexa_custom/actions.py`: Complete overhaul of `_run_action` to use a registry pattern.
- Audio pipeline performance will improve due to peak calculation fixes.
- System stability will improve during network interruptions due to exponential backoff.
