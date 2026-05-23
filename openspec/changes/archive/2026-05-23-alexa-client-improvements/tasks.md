## 1. Action Registry Implementation

- [x] 1.1 Create `ActionRegistry` class in `alexa_custom/actions.py` to support decorator-based handler registration.
- [x] 1.2 Refactor `_run_action` to use the `ActionRegistry` dispatcher, passing necessary context.
- [x] 1.3 Migrate existing action logic (`log`, `telegram`, `livekit_join`, `say`, `ask`, `tone`, `shell`, `mqtt_publish`) into distinct registered handler functions within `actions.py`.
- [x] 1.4 Update existing tests in `test_client.py` or create a new test file to verify the registry dispatcher logic.

## 2. Audio Peak Optimization

- [x] 2.1 Update `calculate_peak` in `alexa_custom/client.py` to calculate the max absolute value directly from the `int16` numpy array before dividing by 32768.0.
- [x] 2.2 Verify `TestClientUtils.test_calculate_peak_*` tests in `tests/test_client.py` still pass with the optimized logic.

## 3. Session Manager Abstraction

- [x] 3.1 Create `LiveKitSessionManager` class in `alexa_custom/client.py` encapsulating `Room`, track management, and events.
- [x] 3.2 Refactor `run_session` body into `LiveKitSessionManager.connect` and `LiveKitSessionManager.disconnect`.
- [x] 3.3 Ensure volume tap tasks and empty room watchdogs are correctly managed within the class lifecycle.
- [x] 3.4 Update `TestClientAsync.test_run_session_basic` in `tests/test_client.py` to mock and verify the new `LiveKitSessionManager` behavior.


## 4. Exponential Backoff Implementation

- [x] 4.1 Update the reconnect loop in `_async_main` within `alexa_custom/client.py` to track failure counts.
- [x] 4.2 Implement logic to double the `RECONNECT_DELAY` after consecutive failures, capping at 30 seconds.
- [x] 4.3 Reset the backoff delay when a successful connection is established.

## 5. Final Verification

- [x] 5.1 Run all unit tests (`pytest`).
- [x] 5.2 Validate client runs without syntax errors or immediate crashes.
