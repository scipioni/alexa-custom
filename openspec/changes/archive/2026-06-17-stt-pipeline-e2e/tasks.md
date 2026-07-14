## 1. Test Infrastructure

- [x] 1.1 Implement `FakeProc` — os.pipe-backed proc that streams silent PCM chunks on a daemon thread, closes pipe when done
- [x] 1.2 Implement `ScriptedBackend` — STTBackend that fires `endpoint=True` after N silent chunks per transcript, pops from FIFO queue; sets `stop_event` after last transcript; `recreate()` is a no-op
- [x] 1.3 Implement `run_pipeline(script, config, timeout=5.0)` helper — monkeypatches `alexa_custom.stt.start_capture` and `alexa_custom.stt.get_stt_backend`, mocks `alexa_custom.actions.get_engine` with a no-op `say()`, calls `start_stt_thread`, joins thread, returns collected events

## 2. Core Scenario Tests

- [x] 2.1 `TestTwoStepWakeCommand` — script `["ehi galileo", "che ore sono"]`, assert `wake` then `matched` in events
- [x] 2.2 `TestTwoStepWakeNoMatch` — script `["ehi galileo", "blah blah blah"]`, assert `wake` present and no `matched`
- [x] 2.3 `TestOneBreath` — script `["ehi galileo che ore sono"]`, assert `wake` and `matched` both present
- [x] 2.4 `TestDirectTrigger` — script `["chiama stefano"]` with `with_wake=False` trigger, assert `matched` present and no `wake`
- [x] 2.5 `TestGatedTriggerNoWake` — script `["che ore sono"]` with only a gated trigger, assert no `matched`

## 3. Reply Window Tests

- [x] 3.1 `TestReplyWindowMatch` — script `["ehi galileo", "chiama stefano", "si"]` with `ask` trigger, assert `wake`, first `matched` for `"chiama stefano"`, second `matched` for `"si"`
- [x] 3.2 `TestReplyWindowTimeout` — script `["ehi galileo", "chiama stefano"]` with reply timeout < 1s, assert `wake` and first `matched` but no second `matched`

## 4. Skill

- [x] 4.1 Create `.claude/skills/test-stt-pipeline/SKILL.md` — skill that runs `uv run pytest tests/test_pipeline_e2e.py -v`, reports pass/fail per scenario, shows event trace on failure
