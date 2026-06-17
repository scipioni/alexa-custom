# Capability: STT Pipeline End-to-End Tests

## Purpose

Integration test suite that drives the full `run_stt_worker` → `_recognition_loop` → `on_stt_event` path using a scripted backend (no real microphone or STT model). Covers wake detection, command matching, direct triggers, one-breath mode, and reply windows.

---

## Requirements

### Requirement: Pipeline harness drives full recognition loop
The test suite SHALL provide a `run_pipeline(script, config)` helper that injects a `ScriptedBackend` and `FakeProc` into `run_stt_worker`, collects all `on_stt_event` events, and returns them as a list of `(event_name, data)` tuples after the worker thread exits.

#### Scenario: Thread exits cleanly after all transcripts consumed
- **WHEN** `run_pipeline` is called with a finite script
- **THEN** the worker thread exits within 5 seconds and `run_pipeline` returns without hanging

#### Scenario: All emitted events are captured
- **WHEN** the recognition loop emits events via `on_stt_event`
- **THEN** every event appears in the returned list in emission order

---

### Requirement: Two-step wake-then-command fires match
The harness SHALL support a scenario where wake word and command are separate utterances.

#### Scenario: Wake word followed by matched command
- **WHEN** script is `["ehi galileo", "che ore sono"]` and config has `"che ore sono"` as a gated trigger
- **THEN** returned events contain a `wake` event followed by a `matched` event

#### Scenario: Wake word followed by unmatched command
- **WHEN** script is `["ehi galileo", "blah blah blah"]` and no trigger matches
- **THEN** returned events contain a `wake` event and a `nomatch` event, but no `matched` event

---

### Requirement: One-breath wake+command fires match
The harness SHALL support a scenario where wake word and command arrive in a single transcript.

#### Scenario: Combined utterance triggers one-breath path
- **WHEN** script is `["ehi galileo che ore sono"]` and config has `"che ore sono"` as a gated trigger
- **THEN** returned events contain a `wake` event and a `matched` event

---

### Requirement: Direct trigger fires without wake word
The harness SHALL verify that triggers with `with_wake=False` fire without a preceding wake word.

#### Scenario: Direct trigger matched without wake
- **WHEN** script is `["chiama stefano"]` and config has `"chiama stefano"` as a direct trigger
- **THEN** returned events contain a `matched` event and no `wake` event

---

### Requirement: Gated trigger does not fire without wake word
The harness SHALL verify that triggers with `with_wake=True` are suppressed when no wake word was detected.

#### Scenario: Gated trigger suppressed when not woken
- **WHEN** script is `["che ore sono"]` and config has `"che ore sono"` as a gated trigger only
- **THEN** returned events contain no `matched` event

---

### Requirement: Reply window receives scripted response
The harness SHALL support a scenario where an `ask` trigger dispatches a reply window and a scripted reply is matched.

#### Scenario: Ask trigger → scripted reply matched
- **WHEN** script is `["ehi galileo", "chiama stefano", "si"]`, config has `"chiama stefano"` as a gated `ask` trigger with `on_reply` containing `"si"`
- **THEN** returned events contain a `wake` event, a `matched` event for `"chiama stefano"`, and a second `matched` event for `"si"`

#### Scenario: Ask trigger → no reply → on_else fires
- **WHEN** script is `["ehi galileo", "chiama stefano"]` (no reply utterance) and the reply window times out
- **THEN** returned events contain `wake` and `matched` for `"chiama stefano"`, and no second `matched` event

---

### Requirement: Skill runs and reports pipeline test results
A Claude Code skill SHALL exist at `.claude/skills/test-stt-pipeline/` that runs `tests/test_pipeline_e2e.py` and reports which scenarios passed or failed.

#### Scenario: Skill invoked successfully
- **WHEN** the skill is invoked
- **THEN** it runs the test suite and reports pass/fail per test scenario with the event trace on failure
