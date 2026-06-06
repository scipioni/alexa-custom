## MODIFIED Requirements

### Requirement: Background MQTT client
The system SHALL maintain a persistent, asynchronous background connection to an MQTT broker. Connection parameters (host, port) MUST be configurable via environment variables. The outgoing message queue SHALL be bounded by `mqtt_queue_max` (from config, default 200). When the queue is full, the oldest pending message SHALL be dropped and a warning SHALL be logged before enqueuing the new message.

#### Scenario: MQTT client connects at startup
- **WHEN** MQTT configuration is present in the environment
- **THEN** the client establishes a connection to the broker and starts its background loop

#### Scenario: Queue overflow drops oldest message
- **WHEN** the MQTT broker is unreachable and 201 messages are published
- **THEN** the first message is dropped, a warning is logged, and the queue holds exactly 200 messages

#### Scenario: Queue bound respected under load
- **WHEN** messages are published faster than the broker accepts them for an extended period
- **THEN** the queue size never exceeds `mqtt_queue_max` and memory usage remains bounded

## ADDED Requirements

### Requirement: Offline state on graceful shutdown
When the system shuts down gracefully (before `os.execv()` restart), it SHALL publish an offline/unavailable state to the MQTT broker and disconnect cleanly before the process is replaced.

#### Scenario: Offline published before restart
- **WHEN** a graceful restart is triggered (config change, web dashboard, source watcher)
- **THEN** the MQTT client publishes the offline payload to the state topic and disconnects before `os.execv()` is called

#### Scenario: Disconnect on broker unavailable
- **WHEN** the broker is unreachable at shutdown time
- **THEN** the disconnect attempt times out gracefully (within 500 ms) and `os.execv()` proceeds
