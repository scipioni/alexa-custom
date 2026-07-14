## 1. ActionContext refactor (behavior-preserving, first)

- [x] 1.1 Add `ActionContext` dataclass in `actions.py` holding `telegram_client`, `livekit_connect_fn`, `livekit_connected`, `listen_fn`, `mqtt_client`, `on_stt_event`, `actions_config`
- [x] 1.2 Change `dispatch(trigger, ctx, *, wake_word=None, transcript=None)` and `_run_action(...)` to take the `ActionContext`; update each handler to read fields from `ctx`
- [x] 1.3 Update the 6 `dispatch(...)` call sites in `stt.py` to build one `ActionContext` per worker run and pass it
- [x] 1.4 Run `uv run pytest tests/test_actions.py` and confirm green (no behavioral change)

## 2. Bounded dispatch execution

- [x] 2.1 Add `recognition.dispatch_timeout` (float seconds, default 60.0) to the recognition config dataclass and parser in `config.py`
- [x] 2.2 Wrap each `_dloop.run_until_complete(dispatch(...))` as `run_until_complete(asyncio.wait_for(dispatch(...), timeout=ceiling))`
- [x] 2.3 On `asyncio.TimeoutError`: log the timeout, reset in-loop recognition state via the existing post-turn reset path, and resume the loop
- [x] 2.4 Add a unit test: a dispatch whose coroutine sleeps past the ceiling is aborted, state is reset, and the loop continues (assert no unhandled exception, listening resumes)
- [x] 2.5 Add a unit test: a dispatch completing within the ceiling behaves identically to today

## 3. STT heartbeat + systemd ping gating

- [x] 3.1 Add a shared heartbeat holder (single-element list or small object) created in `run_stt_worker` and exposed to `client.py`
- [x] 3.2 Stamp `heartbeat = time.monotonic()` once per iteration of the main recognition loop (covering idle-listen iterations)
- [x] 3.3 In `client.py`, gate `sd_notify("WATCHDOG=1")` on `time.monotonic() - heartbeat < freshness` where `freshness < WatchdogSec - ping_interval`
- [x] 3.4 Log the resolved `freshness`, ping interval, and detected `WatchdogSec` at startup; keep the gate inert when `should_use_watchdog()` is false
- [x] 3.5 Add a unit test: fresh heartbeat → ping sent; stale heartbeat → ping withheld; watchdog disabled → ping logic unchanged

## 4. Shutdown-responsive sleeps

- [x] 4.1 Replace `time.sleep(2)` in the `stt.py` backend-reload error handlers with `stop_event.wait(2)`
- [x] 4.2 Add/extend a test asserting the reload-error path exits promptly when `stop_event` is set during the wait

## 5. Validation

- [x] 5.1 `task lint` clean
- [x] 5.2 `task test` green (full suite) — 375 passed, 1 skipped; 1 pre-existing failure in test_audio.py unrelated to this change
- [ ] 5.3 Manual smoke on target: wedge a fake long dispatch, confirm recognition resumes after the ceiling and (with systemd watchdog on) a truly hung loop triggers a restart
