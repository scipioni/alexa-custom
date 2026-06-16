## 1. Remove headless-participant from sos_trigger

- [x] 1.1 In `alexa_custom/actions.py`, remove the `livekit_connect_fn()` call in the cloud path — the device should not join the room when SOS_ENDPOINT_URL is set
- [x] 1.2 Remove the `livekit_connect_fn()` call in the local path — the device should not join the room when spawning a local agent
- [x] 1.3 Verify the browser join URL path still works: `sos_trigger` still opens the browser tab for the user — browser_join_url() call is untouched in sos_trigger

## 2. Add caregiver Telegram notification to agent.py

- [x] 2.1 Add `CAREGIVER_CHAT_ID` and `TELEGRAM_BOT_TOKEN` environment variable support to `alexa_agent/agent.py`
- [x] 2.2 Add Telegram HTTP notification function using `httpx` that sends a LiveKit room join link
- [x] 2.3 Add join link generation in `agent.py` (similar to `browser_join_url()`) using the room URL and a generated caregiver token
- [x] 2.4 Add distress phrase detection in `_process_audio()` that triggers the Telegram notification
- [x] 2.5 Add a session-level `notified` flag to prevent duplicate notifications per session
- [x] 2.6 Add caregiver identity token generation (`caregiver-<timestamp>`) for the join link

## 3. Ensure agent stays for full conversation

- [x] 3.1 Verify the agent's `participant_disconnected` handler only triggers when all humans leave, not on "sto bene" — already correct
- [x] 3.2 Update agent's system prompt to not imply "sto bene" ends the conversation
- [x] 3.3 Verify "disconnetti" still works to end the session via `_check_disconnect()` — already correct

## 4. Testing and validation

- [ ] 4.1 Test that `sos_trigger` no longer creates a `headless-participant` in the LiveKit room
- [ ] 4.2 Test that the AI agent joins and stays after "sto bene"
- [ ] 4.3 Test that "non sto bene" sends a Telegram message to the caregiver
- [ ] 4.4 Test that the caregiver can join via the Telegram link
- [ ] 4.5 Test that duplicate "non sto bene" does not send multiple notifications
- [ ] 4.6 Test that "disconnetti" ends the session for all participants

## 5. Documentation and configuration

- [x] 5.1 Document `CAREGIVER_CHAT_ID` and `TELEGRAM_BOT_TOKEN` environment variables in the project README or docs
- [x] 5.2 Update AGENTS.md with the new SOS flow behavior
