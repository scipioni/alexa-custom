## Why

The existing `test_stt_e2e.py` tests only the raw STT backend layer (audio bytes → transcript text). There is no test that exercises the full recognition pipeline — wake-word detection, with_wake gating, trigger matching, event dispatch, and the reply window — as a wired-together system. Bugs at the integration seams (e.g., the grammar-reset bug after capture_transcript, or the reply window consuming the wrong proc chunks) are invisible to the current test suite.

## What Changes

- **New**: `tests/test_pipeline_e2e.py` — integration test driving the full `run_stt_worker` → `_recognition_loop` → `on_stt_event` pipeline with a `ScriptedBackend` and `FakeProc` instead of a real microphone or acoustic model.
- **New**: `.claude/skills/test-stt-pipeline/SKILL.md` — Claude Code skill to run and interpret the pipeline E2E test suite.

## Capabilities

### New Capabilities

- `stt-pipeline-e2e`: Pipeline-level integration test harness for the STT recognition loop. Covers wake-word detection, command matching, with_wake gating, one-breath firing, direct triggers, and the reply window — all driven by scripted transcripts injected via a fake STT backend, with no real microphone or acoustic model required.

### Modified Capabilities

## Impact

- New file: `tests/test_pipeline_e2e.py`
- New file: `.claude/skills/test-stt-pipeline/SKILL.md`
- No changes to production code
- No new dependencies
