# Capability: Telegram Notification

## Purpose
Send notifications to Telegram chats via the Telegram Bot API.

## Requirements

### Requirement: Send Telegram message on action dispatch
The system SHALL send a message to a configured Telegram chat when a `telegram` action is dispatched. The message is sent via the Telegram Bot API using `httpx`.

#### Scenario: Message sent successfully
- **WHEN** a `telegram` action is dispatched with a valid `chat_id` and `text`
- **THEN** a POST request is made to `https://api.telegram.org/bot<token>/sendMessage` and the message is delivered

#### Scenario: Action-level chat_id overrides default
- **WHEN** the action entry specifies `chat_id: "999"`
- **THEN** the message is sent to chat `999`, not the `TELEGRAM_CHAT_ID` env var default

#### Scenario: Default chat_id used when not in action
- **WHEN** the action entry omits `chat_id`
- **THEN** the message is sent to the chat ID from `TELEGRAM_CHAT_ID` env var

### Requirement: Telegram credentials from environment
The system SHALL read `TELEGRAM_BOT_TOKEN` from the environment. If the token is absent and a `telegram` action is dispatched, the system SHALL log an error and skip the action without crashing.

#### Scenario: Missing bot token
- **WHEN** `TELEGRAM_BOT_TOKEN` is not set and a telegram action fires
- **THEN** an error is logged: "TELEGRAM_BOT_TOKEN not set — telegram action skipped"

#### Scenario: Token present
- **WHEN** `TELEGRAM_BOT_TOKEN` is set
- **THEN** the token is used in the Bot API URL without being logged or exposed

### Requirement: Non-blocking send
The system SHALL send Telegram messages asynchronously so that a slow or failed API call does not block subsequent actions or delay the return to wake word listening.

#### Scenario: API timeout does not block
- **WHEN** the Telegram API does not respond within 5 seconds
- **THEN** the request times out, an error is logged, and the system returns to Stage 1 listening

### Requirement: TelegramClient abstraction
The system SHALL implement Telegram interaction in a `TelegramClient` class with a `send_message(chat_id, text)` async method. The class MUST be structured to allow a future `start_polling(handler)` method without breaking callers of `send_message`.

#### Scenario: send_message callable independently
- **WHEN** `TelegramClient.send_message("123", "hello")` is called
- **THEN** the message is sent without requiring a polling loop to be running
