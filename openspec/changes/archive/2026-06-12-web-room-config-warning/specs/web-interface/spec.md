# Capability: Web Interface

## Delta: Configuration Status in Room Panel

### Modified Requirement: Room panel shows configuration status

The room panel (`#room-panel`) SHALL display the configuration status of LiveKit and Telegram in addition to the normal room status.

When both LiveKit and Telegram are configured (all required env vars non-empty), the room panel SHALL behave exactly as before — showing room connection state (`closed`, `waiting`, `in_call`).

When at least one service is missing configuration, the room panel SHALL override its display:
- Icon becomes `⚠️`
- Label becomes `Calls disabled`
- Subtitle becomes `Missing: LiveKit` / `Missing: Telegram` / `Missing: LiveKit, Telegram`

The configuration check SHALL happen once on WebSocket `hello` and SHALL NOT change during the session (secrets require a full restart).

#### Scenario: Both services configured
- **GIVEN** `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_ROOM`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are all set
- **WHEN** the WebSocket `hello` message has `livekit_configured: true` and `telegram_configured: true`
- **THEN** the room panel shows normal status (`closed`/`waiting`/`in_call`) unchanged

#### Scenario: LiveKit not configured
- **GIVEN** only `LIVEKIT_URL` is missing from env
- **WHEN** the WebSocket `hello` message has `livekit_configured: false`
- **THEN** the room panel displays `⚠️ Calls disabled — Missing: LiveKit`

#### Scenario: Telegram not configured
- **GIVEN** only `TELEGRAM_BOT_TOKEN` is missing from env
- **WHEN** the WebSocket `hello` message has `telegram_configured: false`
- **THEN** the room panel displays `⚠️ Calls disabled — Missing: Telegram`

#### Scenario: Neither configured
- **GIVEN** all LiveKit and Telegram env vars are empty
- **WHEN** the WebSocket `hello` message has both flags `false`
- **THEN** the room panel displays `⚠️ Calls disabled — Missing: LiveKit, Telegram`
