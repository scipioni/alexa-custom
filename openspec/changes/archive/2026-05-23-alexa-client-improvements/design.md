## Context

The `alexa-client` is a headless audio processing application that interfaces with LiveKit, local audio hardware via PipeWire, and MQTT for integration with Home Assistant. The current implementation in `alexa_custom/client.py` and `alexa_custom/actions.py` tightly couples network connection management with audio processing and trigger logic. This design aims to decouple these concerns to improve maintainability, testability, and runtime performance.

## Goals / Non-Goals

**Goals:**
- Extract LiveKit session state management into a dedicated, testable class.
- Decouple action logic from the central dispatcher to allow easy addition of new action types.
- Optimize hot paths (audio peak calculation) to reduce CPU overhead.
- Improve system resilience against network blips with exponential backoff for LiveKit reconnections.

**Non-Goals:**
- We are not changing the configuration schema (`config.yaml`). The current representation of actions and triggers remains identical.
- We are not changing the core STT architecture (Vosk) or TTS engine integration.

## Decisions

### 1. `LiveKitSessionManager` Abstraction
**Decision:** Create a `LiveKitSessionManager` class in `client.py` to handle the `Room` object, track events, and manage reconnections.
**Rationale:** The current `run_session` function in `client.py` is over 150 lines long and handles everything from audio tapping to empty room timeouts. Moving this to a class provides structured state (connected, disconnected, reconnecting) and encapsulates the LiveKit API surface.
**Alternatives Considered:** Leaving the function as is but breaking out helper functions. This doesn't solve the state management issue (currently handled by a web of `asyncio.Event` flags and mutable dictionaries).

### 2. Action Registry Pattern
**Decision:** Implement a decorator-based `ActionRegistry` in `actions.py`.
**Rationale:** The current `_run_action` function uses a long `if/elif` chain. A registry pattern allows action handlers to be defined independently (e.g., `@registry.register("telegram") async def handle_telegram(...)`). This makes adding new actions trivial and allows handlers to be unit-tested in isolation.
**Alternatives Considered:** A dictionary mapping strings to functions. The decorator approach is more idiomatic and self-documenting.

### 3. Optimized Peak Calculation
**Decision:** Modify `calculate_peak` to process `int16` buffers directly.
**Rationale:** The current implementation `float(np.max(np.abs(samples.astype(np.float32)))) / 32768.0` casts the entire audio buffer to 32-bit floats. This occurs on every audio frame (multiple times per second). We will use `float(np.max(np.abs(samples))) / 32768.0` which works directly on the `int16` array, significantly reducing memory allocation.

### 4. Exponential Backoff
**Decision:** Implement a simple exponential backoff for the LiveKit reconnect loop (starting at 2s, doubling up to a max of 30s).
**Rationale:** A fixed 5-second delay (`RECONNECT_DELAY = 5`) can aggressively hammer the server during extended network outages. Exponential backoff is standard practice for network clients.

## Risks / Trade-offs

- **Risk:** Refactoring `run_session` into a class might introduce subtle state bugs if the complex event handling (taps, timeouts) isn't ported correctly.
  - **Mitigation:** Rely on existing tests in `test_client.py` and expand them to cover the new `LiveKitSessionManager` class explicitly before modifying the main loop.
- **Risk:** Action handlers currently expect a large context (telegram client, mqtt client, connect functions). The registry interface needs to handle this gracefully.
  - **Mitigation:** The registry dispatcher will pass a `Context` object (or `kwargs`) containing these dependencies to the handlers.
