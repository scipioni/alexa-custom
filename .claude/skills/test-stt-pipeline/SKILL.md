---
name: test-stt-pipeline
description: Run the pipeline-level integration test suite for the STT recognition loop. Tests drive the full run_stt_worker → _recognition_loop → on_stt_event path using a ScriptedBackend (no real microphone or STT model). Use when you want to verify the recognition pipeline is correctly wired — wake detection, command matching, direct triggers, one-breath, and reply window.
license: MIT
metadata:
  author: stefano.scipioni@csgalileo.net
  version: "1.0"
---

Run the STT pipeline integration tests. These tests exercise the full recognition loop with scripted transcripts — no real microphone, STT model, or network required.

## Steps

1. **Run the test suite**:
   ```
   uv run pytest tests/test_pipeline_e2e.py -v
   ```

2. **Report results** — for each test class, show pass/fail:

   | Scenario | Test | Result |
   |---|---|---|
   | Two-step wake→command | `TestTwoStepWakeCommand` | ✓/✗ |
   | Wake→no match | `TestTwoStepWakeNoMatch` | ✓/✗ |
   | One-breath | `TestOneBreath` | ✓/✗ |
   | Direct trigger | `TestDirectTrigger` | ✓/✗ |
   | Gated trigger suppressed | `TestGatedTriggerNoWake` | ✓/✗ |
   | Reply window match | `TestReplyWindowMatch` | ✓/✗ |
   | Reply window timeout | `TestReplyWindowTimeout` | ✓/✗ |

3. **On failure — show event trace**: When a test fails, the assertion message contains the full event list that was collected. Report it verbatim so it's clear which events fired vs. what was expected. For example:

   ```
   FAILED TestTwoStepWakeCommand::test_wake_then_matched
   AssertionError: no matched event; got ['listening', 'level', 'wake', 'level', 'nomatch', 'listening']
   ```

   This tells you: wake fired correctly, but the transcript didn't match any trigger — likely a fuzzy matching threshold issue or the trigger command string doesn't match the scripted transcript closely enough.

4. **Common failure patterns**:

   - **No `wake` event**: `_match_wake_word` didn't find the wake phrase in the scripted transcript. Check that `config.wake_words` matches exactly what's in the script (case-insensitive, but prefix-boundary aware).
   - **No `matched` event after wake**: The command transcript didn't score above `matching_threshold` (default 70). The scripted transcript must be close enough to a trigger's `commands` list.
   - **Reply window: only 1 matched instead of 2**: `capture_transcript` didn't receive the reply transcript. Check that `ScriptedBackend.recreate()` is a no-op and the FIFO queue still has the reply queued.
   - **Test hangs past timeout**: `stop_event` not set after last transcript. Check `ScriptedBackend` sets `stop_event` after the last `popleft()`.
