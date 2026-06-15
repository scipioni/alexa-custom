## Why

Currently, the companion web dashboard's history is maintained entirely on the client side. This means refreshing the browser or opening it on a new device wipes the entire history of interactions. Furthermore, there is no persistent storage on disk for interaction sessions, which prevents developers and operators from diagnosing system behavior over time—specifically false-positive wake detections, audio calibration, or voice-command mismatches.

## What Changes

- Add a new server-side persistent interaction history in JSONL format, located at `conf/history.jsonl` (configurable).
- Store all critical metadata inside each JSON line needed to debug the system (e.g. false positives, audio gating, wake word, confidence score, VAD status, matched command score, and AI prompt/replies).
- Load the last N interaction history items upon initial page load over WebSocket so the UI is immediately populated.
- Support flagging specific historical items as false positives from the UI, updating the JSONL records on the server.
- Support clearing stored interaction logs securely on the server via the UI's existing "clear" button.

## Capabilities

### New Capabilities
- `persistent-interaction-history`: Introduce persistent, structured logging of wake events, voice commands, action dispatches, and AI replies in JSONL format, integrated with WebSocket and the web UI.

### Modified Capabilities
- `web-interface`: Modify the web interface to display persistent, server-loaded history cards and support flagging false positives and clearing stored backend records.

## Impact

- **Backend:** Adds a state-tracker in `alexa_custom/web.py` to aggregate single-session STT events and write them to `conf/history.jsonl` via threadpool-delegated filesystem writes.
- **Config:** Adds configurable history file path settings in `alexa_custom/config.py`.
- **UI:** Updates `alexa_custom/dashboard.html`, `alexa_custom/static/dashboard.js`, and `alexa_custom/static/dashboard.css` to render interactive persistent cards and communicate user flags back to the backend.
