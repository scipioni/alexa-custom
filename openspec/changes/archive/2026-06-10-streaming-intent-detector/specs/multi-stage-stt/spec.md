## ADDED Requirements

### Requirement: recognition.partial_matching configuration
The `recognition` block in `conf/config.yaml` SHALL accept three new optional keys controlling partial intent matching:

| Field | Type | Default | Description |
|---|---|---|---|
| `partial_matching` | bool | `true` | Enable streaming intent detection on Vosk partial transcripts |
| `partial_stability_ms` | int | `150` | Minimum wall-clock ms a partial match must be stable before firing |
| `partial_stability_reads` | int | `3` | Minimum consecutive matching partial reads before firing |

#### Scenario: Partial matching enabled by default
- **WHEN** `conf/config.yaml` has no `partial_matching` key under `recognition`
- **THEN** `RecognitionConfig.partial_matching` is `True` and streaming intent detection is active

#### Scenario: Partial matching explicitly disabled
- **WHEN** `recognition.partial_matching: false` is set
- **THEN** the partial-matching early-exit block is skipped and stage-1 behaves as before this change

#### Scenario: Custom stability parameters applied
- **WHEN** `partial_stability_ms: 200` and `partial_stability_reads: 4` are set
- **THEN** a partial intent match requires 4 consecutive matching reads AND ≥200ms before `_wake_detected` is called
