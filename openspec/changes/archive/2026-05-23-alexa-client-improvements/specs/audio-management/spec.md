## ADDED Requirements

### Requirement: Optimized peak calculation
The system SHALL calculate audio peak levels directly from raw `int16` sample buffers without casting the entire buffer to floating point numbers, in order to minimize CPU utilization and memory allocation overhead.

#### Scenario: Peak calculation performance
- **WHEN** an audio frame is processed for volume metrics
- **THEN** the peak is derived directly from the integer amplitude before normalization.
