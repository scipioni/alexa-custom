# Capability: Streaming Intent Detection

## Purpose
Continuously scan Vosk partial transcripts for complete (wake + trigger) intents, firing immediately when a match is stable — bypassing the VAD silence wait and reducing response latency.

## Requirements

### Requirement: Intent map built from wake phrases and trigger phrases
The system SHALL build an intent map at config load time by computing the Cartesian product of all normalized wake phrases (from `alias_map`) and all reachable trigger phrases (per-group triggers, falling back to global triggers) plus their aliases. Each entry maps a normalized combined string to `(WakeWordGroup, Trigger)`.

#### Scenario: Intent map populated from config
- **WHEN** wake words include "ehi galileo" (with alias "galileo") and triggers include phrase "chiama stefano"
- **THEN** intent_map contains keys "ehi galileo chiama stefano" and "galileo chiama stefano", both mapping to the same (group, trigger) pair

#### Scenario: Per-group triggers shadow global triggers
- **WHEN** a wake group has its own triggers and global triggers also exist
- **THEN** intent_map entries for that group use the per-group triggers only (matching `_resolve_triggers` behaviour)

#### Scenario: Intent map rebuilt on hot-reload
- **WHEN** `conf/config.yaml` is modified to add a new trigger phrase while the daemon is running
- **THEN** the intent map is rebuilt within one config-poll cycle and the new combo becomes matchable

### Requirement: Partial transcript scanned for full intent match every chunk
When `recognition.partial_matching` is `true` and stage-1 backend is Vosk free-vocabulary (not grammar mode), the system SHALL call `_match_full_intent` on every Vosk partial result. `_match_full_intent` MUST use exact matching only (`_extract_wake_command` with `fuzzy=False`) followed by exact normalized comparison against trigger phrases and their aliases.

#### Scenario: Full intent found in partial
- **WHEN** Vosk partial result is "ehi galileo chiama stefano" and that combo exists in intent_map
- **THEN** `_match_full_intent` returns `(group, trigger)`

#### Scenario: Wake word only in partial — no trigger yet
- **WHEN** Vosk partial result is "ehi galileo" with no following words
- **THEN** `_match_full_intent` returns `None` (inline_cmd is empty)

#### Scenario: Partial contains wake word but command is not a known trigger
- **WHEN** Vosk partial result is "ehi galileo dimmi il meteo" and "dimmi il meteo" is not a configured trigger
- **THEN** `_match_full_intent` returns `None` and the loop falls through to the VAD path

#### Scenario: Fuzzy matching NOT used on partials
- **WHEN** Vosk partial contains a wake-word synonym that is not in alias_map
- **THEN** `_match_full_intent` returns `None` regardless of phonetic similarity

### Requirement: Stability window before intent fires
The system SHALL track consecutive matching reads and elapsed time since the first matching read. A partial intent match SHALL only trigger `_wake_detected` when BOTH of the following conditions hold:
- consecutive identical intent matches ≥ `recognition.partial_stability_reads`
- elapsed time since first match ≥ `recognition.partial_stability_ms`

The stability state SHALL be reset whenever the matched intent changes or returns `None`.

#### Scenario: Match fires after stability threshold
- **WHEN** `_match_full_intent` returns the same intent for 3 consecutive reads spanning 150ms
- **THEN** `_wake_detected` is called with the matched group and inline command

#### Scenario: Flickering partial does not fire
- **WHEN** `_match_full_intent` alternates between a match and `None` across reads
- **THEN** the stability counter resets and `_wake_detected` is not called

#### Scenario: Early reads suppressed
- **WHEN** `_match_full_intent` returns the same intent for only 2 reads (below `partial_stability_reads: 3`)
- **THEN** `_wake_detected` is not yet called

### Requirement: Early-exit resets stage-1 and skips VAD path
When a stable intent match fires, the system SHALL immediately reset the stage-1 recognizer state and `continue` the loop, skipping the VAD/endpoint finalization block entirely for that chunk.

#### Scenario: No double-fire after early exit
- **WHEN** a partial match fires and stage-1 is reset
- **THEN** the subsequent VAD finalization of the same utterance does not call `_wake_detected` a second time

### Requirement: Partial matching disabled in grammar mode and for non-Vosk backends
The system SHALL skip partial matching when `stt.stage1.vosk_grammar` is `true` or when the stage-1 backend is not a Vosk free-vocabulary recognizer.

#### Scenario: Grammar mode bypasses partial matching
- **WHEN** `stt.stage1.vosk_grammar: true` is configured
- **THEN** the partial-matching block is not executed and existing grammar-mode behaviour is unchanged

#### Scenario: Sherpa-onnx KWS path unaffected
- **WHEN** stage-1 backend is sherpa-onnx keyword spotter
- **THEN** partial matching code is not reached (different branch in `_run_stt_loop`)
