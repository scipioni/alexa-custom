## ADDED Requirements

### Requirement: Registration
The system SHALL register a `say_date` action type in the action registry.

#### Scenario: Type is registered
- **WHEN** the `actions` module is imported
- **THEN** `registry._handlers` SHALL contain a handler for `"say_date"`

### Requirement: Italian date pronunciation
The `say_date` action SHALL speak the current date using hardcoded Italian day and month names, independent of system locale.

#### Scenario: Default format
- **WHEN** the action is dispatched with no `format` parameter
- **THEN** the system SHALL speak the date in the default format `Oggi è {weekday} {day} {month} {year}`

#### Scenario: Custom format
- **WHEN** the action is dispatched with `format: "Oggi è {weekday}"`
- **THEN** the system SHALL speak only `Oggi è sabato` (or the current weekday)

#### Scenario: Italian names
- **WHEN** the action is dispatched on any day of the year
- **THEN** the weekday SHALL be one of `["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]`
- **AND** the month SHALL be one of `["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]`

### Requirement: Locale independence
The `say_date` action MUST NOT depend on any system locale setting (`LANG`, `LC_TIME`, `LC_ALL`).

#### Scenario: C locale
- **WHEN** the system locale is set to `C`
- **THEN** the spoken date SHALL still use Italian day and month names
