## 1. Config and Persistence Layer Setup

- [x] 1.1 Add an optional configurable `history_file` field to `WebConfig` in `alexa_custom/config.py` defaulting to `"conf/history.jsonl"`.
- [x] 1.2 Implement a non-blocking, threadpool-delegated filesystem append function `_append_history_log(session_data)` in `WebServer` (`alexa_custom/web.py`) using `loop.run_in_executor`.
- [x] 1.3 Implement file-truncating function `_clear_history_log()` in `WebServer` to safely clear persistent log records on disk.
- [x] 1.4 Implement a file lock-protected update function `_flag_history_log_fp(session_id)` in `WebServer` to locate a record by ID and toggle its false positive flags in-place.

## 2. Server-Side Session Aggregation Logic

- [x] 2.1 Add `self._active_session` state variable in `WebServer` to store the active session details.
- [x] 2.2 Update `on_stt_event` callback in `web.py` to initialize a new session object on `"wake"` containing timestamp, session_id, and wake word.
- [x] 2.3 Accumulate partial transcripts, gating statuses, command match status/scores, and LLM reply values into `self._active_session` as STT events flow.
- [x] 2.4 Finalize, persist, and broadcast the consolidated session on terminal events (transition back to `"sleeping"`, `"listening"`, `"llm_reply"`, or on a new `"wake"` event) and reset the active session state.

## 3. WebSocket Handshake and Control Messages

- [x] 3.1 Implement a fast-tail reader in `web.py` to parse the last 20 entries of `history.jsonl` on startup and send them as the `history` array in the initial `"hello"` WebSocket handshake.
- [x] 3.2 Intercept `"clear_history"` and `"flag_fp:<id>"` commands in the WebSocket's `_handle_control` loop.
- [x] 3.3 Broadcast `"history_cleared"` and `"history_flagged"` events respectively to all active WS clients to trigger synchronized UI state transitions.

## 4. UI Rendering and Dashboard Operations

- [x] 4.1 Update `alexa_custom/dashboard.html` to establish template container bindings and structure for unified history items.
- [x] 4.2 Rewrite `clearHistory()` in `static/dashboard.js` to dispatch the `"clear_history"` control command via WebSockets instead of just clearing local memory.
- [x] 4.3 Replace client-side history appending in JS with a unified rendering function `addSessionHistory(sessionData)` that accepts and renders the structured backend records.
- [x] 4.4 Add event listener for `[Flag FP]` button on history cards to dispatch `"flag_fp:<session_id>"` command via WebSockets.
- [x] 4.5 Add style classes in `static/dashboard.css` to visually dim, apply warning borders, and disable flagging buttons on flagged false-positive history cards.

## 5. Testing & Validation

- [x] 5.1 Create `tests/test_persistent_history.py` to test session aggregation, file persistence, clear/flag controls, and multi-client websocket synchronization.
- [x] 5.2 Run the workspace test suite to verify implementation correctness and check for any regressions.
