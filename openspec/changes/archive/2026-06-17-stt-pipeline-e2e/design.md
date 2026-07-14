## Context

The STT pipeline in `alexa_custom/stt.py` wires together: audio capture (`start_capture`), a backend (`get_stt_backend`), and the recognition loop (`_recognition_loop`). The loop drives wake-word detection, with_wake gating, trigger matching, and event dispatch — including nested `capture_transcript` calls for reply windows. Past bugs (grammar not reset after reply window, partial events flooding on unchanged text) were invisible to the existing test suite because it only tests the backend layer or individual logic functions.

## Goals / Non-Goals

**Goals:**
- Exercise the full `run_stt_worker` → `_recognition_loop` → `on_stt_event` path in a fast, deterministic test
- Cover: wake-word detection, two-step wake→command, one-breath, direct triggers, with_wake gating, reply window
- No real microphone, no acoustic model, no network calls required
- Tests run in < 5 seconds total

**Non-Goals:**
- Acoustic accuracy (does Vosk correctly transcribe real speech?) — that is `test_stt_e2e.py`'s job
- TTS fidelity (does piper produce the right audio?)
- Benchmark / performance measurement

## Decisions

### D1: Scripted backend over real STT model

Inject a `ScriptedBackend` that delivers pre-canned transcripts on demand instead of decoding real audio. This keeps tests deterministic and fast (< 100ms per scenario) without requiring model files.

**Alternative considered**: Use real Vosk with piper-synthesized audio. Rejected for integration tests because: (a) slow (model load ~0.4s, synthesis ~2s per phrase), (b) flaky on accent/noise, (c) tests acoustic accuracy rather than pipeline wiring.

`ScriptedBackend` implements the `STTBackend` protocol:
- `accept_waveform(data) → bool`: returns `True` (endpoint) after a fixed number of chunks, cycling through the script queue
- `text() → str`: pops and returns next transcript
- `partial_text() → str`: returns `""` (no partials needed for integration tests)
- `reset()`: no-op
- `finalize() → str`: returns `""` (endpoint path always used)
- `recreate(grammar)`: no-op (grammar ignored; next transcript in queue is served regardless)

After the last transcript is popped, `ScriptedBackend` sets `stop_event` to terminate the worker thread cleanly.

### D2: FakeProc over real parec

Inject a `FakeProc` that writes silent PCM to an `os.pipe()` on a daemon thread, so `_recognition_loop`'s `proc.stdout` reads never block. Silent audio keeps `rms < rms_threshold`, so no adaptive-RMS drift or spurious partial events. The `ScriptedBackend` fires endpoints independently of RMS — the `endpoint` branch in the loop is used, bypassing the VAD silence timer entirely.

### D3: Monkeypatch at module level

Two monkeypatches applied per test run:
- `alexa_custom.stt.start_capture` → factory that returns `FakeProc`
- `alexa_custom.stt.get_stt_backend` → factory that returns `ScriptedBackend`
- `alexa_custom.actions.get_engine` → returns a mock with a no-op `say()` (silences TTS during `ask` dispatch)

Applied via `monkeypatch` fixture (pytest) for automatic teardown.

### D4: Test config uses side-effect-free actions

Test triggers use `type: log` for non-ask scenarios so no TTS, network, or filesystem side effects occur. The `ask` scenario mocks `get_engine().say`.

### D5: Reply window coverage via script ordering

The `ask` action calls `capture_transcript` on the same `proc.stdout`. Since `ScriptedBackend` serves transcripts in FIFO order and `recreate()` is a no-op, the third item in the script is naturally consumed by the reply window without any special wiring.

Script for reply scenario: `["ehi galileo", "chiama stefano", "si"]`

### D6: Skill as a thin wrapper

The `.claude/skills/test-stt-pipeline/SKILL.md` skill runs `uv run pytest tests/test_pipeline_e2e.py -v`, then interprets and reports the output. No additional infrastructure needed.

## Risks / Trade-offs

- **Scripted backend bypasses RMS/VAD entirely**: Tests won't catch regressions in the `speech_ms` accumulation or adaptive-RMS paths. Acceptable — those paths are covered by `test_wake_detection.py`.
- **`recreate()` no-op means grammar logic untested**: The reply window grammar switch is not exercised by integration tests. Acceptable — it is covered by unit tests on `VoskSTT.recreate()` and was already fixed.
- **Thread timing**: `stop_event` is set inside `ScriptedBackend.text()` after the last transcript. The worker loop's `while not stop_event.is_set()` check runs at the top of the next iteration. There is a narrow window where one extra `_recognition_loop` iteration starts. Mitigated by `FakeProc` writing only a finite amount of PCM; the loop exits on EOF before starting again.
