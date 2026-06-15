## ADDED Requirements

### Requirement: Session aggregation and state tracking
The backend WebServer SHALL aggregate fragmented STT and AI lifecycle events (including wake word triggers, partial/final transcripts, action dispatches, and LLM replies) into a single unified interaction session object.

#### Scenario: Complete successful interaction
- **WHEN** the backend receives a "wake" event followed by "transcribing", "matched", and "llm_reply"
- **THEN** it aggregates these events into a single unified session object with unique ID, timestamp, wake details, transcript text, dispatched action type, and AI reply

#### Scenario: Gated audio or abandoned trigger
- **WHEN** the backend receives a "wake" event followed by "gated" or transitions back to "sleeping" without a transcript
- **THEN** it aggregates these events as a completed session with empty transcript text and sets the gated or timeout flags in the diagnostics block

### Requirement: Disk persistence in JSONL format
The system SHALL persist each completed interaction session by appending it as a single JSON-encoded line to a local history file (default: `conf/history.jsonl`) asynchronously using a threadpool executor to prevent blocking the async event loop.

#### Scenario: Persistent record written
- **WHEN** an interaction session is completed
- **THEN** the server serializes the session structure to a JSON string and appends it with a newline to `conf/history.jsonl`

### Requirement: Safe server-side clearing
The WebServer SHALL support clearing the stored persistent logs upon receiving a clear request.

#### Scenario: Truncate history file
- **WHEN** a "clear_history" control command is received
- **THEN** the server truncates `conf/history.jsonl` to size 0, releases any resources, and broadcasts a "history_cleared" websocket message to all connected clients

### Requirement: In-place false positive flagging
The WebServer SHALL support flagging a past interaction record as a false positive in the persistent file.

#### Scenario: Record updated in-place
- **WHEN** a "flag_fp" control command is received with a specific session ID
- **THEN** the server acquires a file lock, reads `conf/history.jsonl`, locates the corresponding session ID line, sets its "false_positive" and "user_flagged" flags to true, rewrites the file atomically, and broadcasts a "history_flagged" websocket message with that session ID
