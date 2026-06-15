## Context

The companion Python web server (`WebServer` in `alexa_custom/web.py`) uses an async WebSockets connection to push live STT, LLM, and audio volume events to a single-page web dashboard. Currently, all historical interactions are managed entirely in client-side memory (`static/dashboard.js`). As a result, reloading the dashboard or opening it on a new device wipes the history list. Operators also lack any persistent record of voice events, making it difficult to analyze and debug "false-positive" wake triggers (where ambient noise or TV audio activates the system) without digging through dense, raw terminal stderr output.

## Goals / Non-Goals

**Goals:**
- Implement a lightweight, zero-dependency, and persistent backend history store in JSONL format.
- Aggregrate fragmented STT/AI events (`wake`, `transcribing`, `matched`/`nomatch`, `llm_reply`) into a single, cohesive session model on the server before writing to disk.
- Deliver the last N complete history items to the web UI during the initial handshake.
- Support flagging specific history items as "false positives" from the UI and modifying their persistent state on disk.
- Bind the existing dashboard "clear" button to truncate the backend history file.

**Non-Goals:**
- Storing raw WAV audio binary files directly within the history file (the system already supports storing raw pre-trigger WAVs in `dump_triggers_dir` if configured).
- Setting up an external relational database (e.g., SQLite or Postgres) when a lightweight JSONL file fits the single-board/embedded nature of the device.

## Decisions

### Decision 1: JSONL Append-Only Log over Relational Database
- **Choice:** Persistent flat JSONL file (`conf/history.jsonl`).
- **Rationale:** Writing is a simple append-only operation, which is highly efficient. It is zero-dependency, extremely easy to copy or back up, and easily inspectable by shell utilities (`grep`, `tail`, `jq`).
- **Alternatives Considered:** 
  - *SQLite:* Adds schema-management, migrations, and file-locking overhead. Unnecessary for simple log rows.
  - *Raw Text logs:* Too unstructured to parse reliably when loading the web UI.

### Decision 2: Server-Side State Aggregation
- **Choice:** The `WebServer` tracks an active session dict (`self._active_session`) in memory. It initializes on `wake`, accumulates partials and dispatches, and flushes/persists when the lifecycle transitions back to `listening` or `sleeping` or upon terminal states (like `llm_reply` or a new `wake` event).
- **Rationale:** Simplifies the client-side code dramatically. Instead of the client stitching together separate WebSocket messages, it receives a single `history_item` packet.
- **Alternatives Considered:** 
  - *Client-side aggregation:* Fails to persist the data if the user closes or reloads the tab before a session completes.

### Decision 3: Non-Blocking File I/O via Async Executors
- **Choice:** File writes (append and rewrite) are run in the loop's default threadpool executor (`run_in_executor`).
- **Rationale:** Prevents blocking the main asyncio event loop during disk accesses (especially on slower SD cards in Raspberry Pi systems).
- **Alternatives Considered:**
  - *Synchronous writing on the main loop:* Can cause micro-stutters and audio glitches in the real-time STT pipeline.

### Decision 4: Atomic In-Place Flag Updates with File Locks
- **Choice:** Flagging an item as a false positive reads the JSONL, replaces the JSON string of the target `session_id`, and rewrites the file atomically under the protection of a file lock.
- **Rationale:** Keeps the history file correct and consistent. The existing `_file_lock` helper in `web.py` can be reused to guarantee thread/process safety.
- **Alternatives Considered:** 
  - *Log a new "correction" line:* Harder for the initial handshake to reconstruct the state without scanning the entire file and stitching corrections.

## Risks / Trade-offs

- **[Risk] History file grows too large over months**  
  → *Mitigation:* The JSONL lines are compact (averaging 500 bytes per session). Even 10,000 interactions consume less than 5MB. The web UI includes a "clear" button that truncates the file back to 0 bytes, giving the operator full control.
- **[Risk] Concurrent writes from multiple WebSockets flagging items**  
  → *Mitigation:* Use `run_in_executor` combined with the existing process/thread-safe `_file_lock` context manager when rewriting the JSONL file during a flagging action.
