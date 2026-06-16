## Context

The SOS flow is triggered via wake word + "emergenza" which dispatches the `sos_trigger` action. Currently the device joins as `headless-participant`, spawns `alexa_agent/agent.py` as a subprocess (or POSTs to a cloud endpoint), and opens a browser tab. The agent (`agent.py`) leaves when the user leaves the room (`participant_disconnected`), and has no concept of caregiver escalation.

## Goals / Non-Goals

**Goals:**
- Remove `headless-participant` from the SOS room — only the AI agent and the browser user join
- AI agent stays in the room until the user says "disconnetti" or leaves the room
- When the user says "non sto bene", the agent sends a Telegram notification to a caregiver with a LiveKit room join link
- Caregiver opens the link and joins the same LiveKit room as a real human participant
- Minimal changes to existing agent code

**Non-Goals:**
- No changes to `agent_session` or non-SOS LiveKit flows
- No changes to the MQTT-based cloud SOS path (unless needed)
- No caregiver UI or dashboard beyond Telegram
- No persistence of caregiver sessions

## Decisions

### 1. Telegram notification originates from `alexa_agent/agent.py`
**Why**: The subprocess agent is the one that understands conversation context — it knows when the user has said "non sto bene". Signaling back to the parent process (device) would require IPC (MQTT, pipe, HTTP) and add complexity. Instead, the agent receives caregiver credentials via environment variables and sends Telegram directly using `httpx`.

**Alternatives considered:**
- Device-side MQTT → agent publishes MQTT, device picks it up and sends Telegram. Rejected: adds latency, MQTT dependency, and failure mode if broker is down.
- Direct HTTP from agent to Telegram API. Chosen: simplest, agent already has HTTP dependencies.

### 2. No `livekit_connect_fn()` call in `sos_trigger`
**Why**: The `headless-participant` (the device as a room participant) is unnecessary. The user interacts through the browser tab. The device's only role is to detect the wake word, trigger the SOS flow, and open the browser. Audio capture/playback is handled by the browser.

**Impact**: Remove `await livekit_connect_fn()` calls at lines 369-371 (cloud path) and 391-393 (local path) in `alexa_custom/actions.py`.

### 3. Agent stays until "disconnetti" or all participants leave
**Why**: The current agent exits only on `participant_disconnected` (lines 418-421 of agent.py). This is already correct — when the user closes the browser tab, the agent leaves. For "sto bene" we simply don't add any special exit logic; the agent continues conversation as normal.

**Change**: No changes needed to the exit-on-participant-disconnect logic. Only ensure the agent's system prompt is updated to not confuse "sto bene" with "end conversation".

### 4. Caregiver join link uses the same room as the SOS call
**Why**: The caregiver needs to talk directly with the user. Using the same LiveKit room is the simplest. The agent stays in the room alongside the user and caregiver.

**Implementation**: Generate a token with identity `caregiver-<timestamp>` using the existing `make_browser_token()` or `_generate_agent_tokens()` infrastructure, and embed it in a `meet.livekit.io` URL.

### 5. "Non sto bene" detection in agent.py
**Why**: The agent's `_process_audio` loop already processes STT output. Adding a phrase check before/after the LLM call is minimal.

**Implementation**: In `_handle_llm()` or `_process_audio()`, check if the user's utterance contains distress keywords ("non sto bene", "aiuto", "chiama aiuto", etc.). If matched, fire the Telegram notification asynchronously without blocking the conversation flow.

## Risks / Trade-offs

- **[Risk] Telegram API unreachable**: If Telegram is down, the caregiver never receives the notification. *Mitigation*: the agent logs the error and continues the conversation; the caregiver is not alerted but the user still has the AI agent.
- **[Risk] Caregiver doesn't respond**: The caregiver may not be available. *Mitigation*: the agent stays in the room and can offer alternatives ("Vuoi che chiami qualcun altro? Preferisci che ripeta?").
- **[Risk] False positive "non sto bene" detection**: The user might say "non sto bene" as a passing comment. *Mitigation*: use the LLM's semantic understanding rather than simple keyword matching — let the LLM decide if the user is actually in distress.
- **[Trade-off] Telegram instead of MQTT**: Telegram is already integrated on the device side; adding it to the agent subprocess duplicates credential management. Acceptable for simplicity — caregiver credentials are passed as env vars.
- **[Risk] Multiple notifications**: If the user repeats "non sto bene", the caregiver gets spammed. *Mitigation*: agent sets a flag after the first notification and does not re-notify within the same session.

## Open Questions

- Should the agent notify the caregiver proactively ("stai bene?") or wait for the user to say "non sto bene"? Currently: wait for user.
- What conversation flow after the caregiver joins? Should the agent introduce them? ("Ecco il tuo caregiver, Giovanni") — Yes, that would be helpful.
