## ADDED Requirements

### Requirement: Shell tool validated against allowlist
The system SHALL check every `shell` tool call's command string against a configurable allowlist of glob patterns before execution. Commands not matching any pattern SHALL be rejected with an error result.

#### Scenario: Allowed command executed
- **WHEN** the LLM calls `shell` with command `uptime` and `uptime` is in the allowlist
- **THEN** the shell command SHALL execute and the result SHALL be fed back

#### Scenario: Disallowed command rejected
- **WHEN** the LLM calls `shell` with command `rm -rf /` and the allowlist does not contain `rm*`
- **THEN** the system SHALL NOT execute the command and SHALL return an error result "command not allowed"

#### Scenario: Wildcard pattern matching
- **WHEN** the allowlist contains `mosquitto_pub *` and the LLM calls `shell` with `mosquitto_pub -t home/light -m on`
- **THEN** the command SHALL match and be executed

### Requirement: Allowlist configurable via LLM config
The system SHALL support an optional `shell_allowed_commands` list in the LLM configuration section.

#### Scenario: Default allowlist
- **WHEN** `shell_allowed_commands` is not set in config
- **THEN** the system SHALL use a safe default allowlist containing basic read-only commands (`uptime`, `date`, `whoami`, `uname -a`, `ls *`)

#### Scenario: Custom allowlist
- **WHEN** `shell_allowed_commands` is set to `["publish *", "uptime", "date"]`
- **THEN** only those patterns SHALL be allowed; the default SHALL NOT apply
