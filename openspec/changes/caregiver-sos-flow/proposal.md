## Why

The current SOS flow ("emergenza") connects three participants to the LiveKit room: the device (`headless-participant`), the AI agent, and a browser tab for the user. The device as a separate participant is unnecessary — the user interacts through the browser. More importantly, when the user says "non sto bene" there is no way to alert a real human (caregiver) to join and help. The AI agent should stay in the room for the whole conversation, not leave when the user says they're fine.

## What Changes

- **Remove `headless-participant`**: `sos_trigger` no longer calls `livekit_connect_fn()` — only the AI agent and the browser user join the room
- **AI agent stays for the full conversation**: when the user says "sto bene", the agent does NOT leave — it remains available for voice interaction until the user hangs up
- **"Non sto bene" triggers caregiver notification**: when the user signals distress, the system sends a Telegram message with a LiveKit join link to the caregiver
- **Caregiver joins as a human participant**: the caregiver opens the link and enters the same LiveKit room as a real person (not AI), able to speak directly with the user
- **No changes to `agent_session` or other flows**: only the SOS/emergency path is affected

## Capabilities

### New Capabilities
- `caregiver-notify`: Sends a Telegram notification to a pre-configured caregiver with a LiveKit room join link when the user says "non sto bene" during an SOS call

### Modified Capabilities
- `sos-trigger`: The existing SOS trigger action is modified — removes the `livekit_connect_fn()` call (no `headless-participant`), changes AI agent behaviour to stay for the full conversation, and adds caregiver notification on distress

## Impact

- `alexa_custom/actions.py`: modify `sos_trigger` handler — remove `livekit_connect_fn()` calls in both cloud and local paths, add caregiver Telegram notification logic
- `alexa_agent/agent.py`: change the AI agent to not auto-exit on "sto bene" — instead stay until the room is empty or the user explicitly disconnects
- `conf/actions/user.yaml` or `conf/actions/system.yaml`: ensure the SOS trigger maps to `sos_trigger` action type (no change needed if already configured)
- **New config**: caregiver Telegram chat ID and optional caregiver phone/contact info in environment variables
