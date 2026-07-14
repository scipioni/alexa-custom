## ADDED Requirements

### Requirement: system_info action reads and speaks system vitals
The system SHALL provide a `system_info` action type that, when dispatched, reads CPU temperature, 1-minute load average, free memory, and uptime from the host OS and speaks a single natural Italian sentence via the TTS engine.

#### Scenario: All vitals available
- **WHEN** the `system_info` action is dispatched
- **THEN** the system reads CPU temperature from `/sys/class/thermal/thermal_zone*/temp`, load average from `/proc/loadavg`, free memory from `/proc/meminfo`, and uptime from `/proc/uptime`
- **THEN** it speaks one Italian sentence combining all four values (e.g., "Il sistema è a 43 gradi, carico 1.7, venti gigabyte liberi, attivo da un giorno e tredici ore.")

#### Scenario: No thermal zone available
- **WHEN** no `/sys/class/thermal/thermal_zone*/temp` file is readable
- **THEN** the system omits the temperature from the spoken sentence and speaks the remaining vitals

### Requirement: system_info action takes no params
The `system_info` action SHALL require no `params` in the YAML trigger definition. Language is always Italian; all vitals are always included.

#### Scenario: Trigger with empty or absent params
- **WHEN** a trigger defines `type: system_info` with no `params` key
- **THEN** the action executes successfully without error

### Requirement: Example trigger in user.yaml
The `conf/actions/user.yaml` file SHALL contain a commented-out example trigger for `"come sta il sistema"` using the `system_info` action type, consistent in style with existing commented examples in that file.

#### Scenario: Example is present and commented out
- **WHEN** a user opens `conf/actions/user.yaml`
- **THEN** they find a commented-out `system_info` trigger block they can uncomment to activate
