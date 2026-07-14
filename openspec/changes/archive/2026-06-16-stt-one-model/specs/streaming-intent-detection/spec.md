## REMOVED Requirements

### Requirement: Intent map built from wake phrases and trigger phrases
**Reason**: Partial-transcript intent firing is removed. The single-model loop fires on confirmed (endpoint) matches, not on a precomputed wake×trigger intent map scanned against partials.
**Migration**: No config change. One-breath "wake + command" is still supported, but resolved at endpoint time by matching the finalized transcript against wake words and commands (see `command-wake-gating`).

### Requirement: Partial transcript scanned for full intent match every chunk
**Reason**: The system no longer evaluates partial transcripts for early firing; matching runs on finalized utterances.
**Migration**: Remove `recognition.partial_matching` and `partial_stability_*` from config.

### Requirement: Stability window before intent fires
**Reason**: Stability counting existed to debounce partial-match firing, which is removed.
**Migration**: Remove `recognition.partial_stability_ms` and `recognition.partial_stability_reads`.

### Requirement: Early-exit resets stage-1 and skips VAD path
**Reason**: There is no stage-1 to reset; a single loop handles reset/endpoint uniformly.
**Migration**: None required.

### Requirement: Partial matching disabled in grammar mode and for non-Vosk backends
**Reason**: Grammar mode and the partial-matching feature are both removed.
**Migration**: None required.
