## Why

The STT daemon thread runs each voice turn synchronously on its own dedicated event loop (`_dispatch_loop.run_until_complete(dispatch(...))` in `stt.py`) and can block unboundedly — a wedged `listen_fn`, a stalled LiveKit connect, or a slow LLM freezes wake-word recognition with no upper bound. Meanwhile the systemd watchdog ping (`sd_notify("WATCHDOG=1")`) lives on the *separate* main async loop in `client.py`, so a hung STT thread is never detected: the main loop keeps pinging, systemd stays happy, and the assistant goes silently deaf until a human power-cycles it. The existing `stt-thread-watchdog` capability only catches the thread *exiting* (`is_alive()`), not the far more common alive-but-hung case.

## What Changes

- **STT heartbeat gate on the systemd watchdog**: the STT loop stamps a monotonic `last_alive` timestamp on every iteration; the main loop pings `WATCHDOG=1` only when that stamp is fresh. A hung-but-alive STT thread now lets the systemd watchdog timer expire, triggering an automatic process restart.
- **Bounded dispatch execution**: `run_until_complete(dispatch(...))` is wrapped in `asyncio.wait_for(...)` with a configurable ceiling. On timeout the turn is aborted, in-loop state is reset, the event is logged, and recognition resumes — instead of freezing forever.
- **Shutdown-responsive sleeps**: the blocking `time.sleep(2)` calls in `stt.py` backend-reload error handlers are replaced with `stop_event.wait(2)`, so a stop request is honored immediately instead of after a 2-second deaf window.
- **`ActionContext` refactor**: the ~10 positionally-threaded arguments of `dispatch()` / `_run_action()` (telegram client, livekit connect fn, listen fn, mqtt client, stt-event callback, actions config, …) are collapsed into a single `ActionContext` dataclass passed through the 6 dispatch call sites in `stt.py`. This is done **first** so the dispatch-timeout and any future cancellation/deadline plumbing is a one-field change rather than a six-site edit. No behavioral change.

Non-goal (explicitly out of scope): moving dispatch off the STT thread. Running the turn on that thread is intentional — it prevents recognition while the device is speaking or awaiting a follow-up. This change makes that blocking *bounded and observable*, not eliminated.

## Capabilities

### New Capabilities
- `stt-hang-detection`: Detect an alive-but-hung STT thread via a heartbeat the STT loop stamps each iteration, and gate the systemd `WATCHDOG=1` ping on heartbeat freshness so a hung thread causes an automatic systemd restart. Complements (does not replace) `stt-thread-watchdog`, which handles thread *death*.

### Modified Capabilities
- `action-dispatch`: Add a bounded-execution requirement — a dispatched turn that exceeds a configurable time ceiling is aborted, recognition state is reset, and listening resumes, rather than blocking the STT thread indefinitely.

## Impact

- **Code**: `alexa_custom/stt.py` (heartbeat stamp, `asyncio.wait_for` around dispatch, `sleep`→`wait`, `ActionContext` at the 6 call sites), `alexa_custom/client.py` (heartbeat-gated `WATCHDOG=1` ping), `alexa_custom/actions.py` (`ActionContext` dataclass; `dispatch()` / `_run_action()` signatures).
- **Config**: new key under `recognition:` for the dispatch timeout ceiling (with a backward-compatible default).
- **systemd**: relies on the existing `Type=notify` + `WatchdogSec` unit; no new dependency. Behavior changes only in *when* `WATCHDOG=1` is sent.
- **Tests**: new unit coverage for heartbeat freshness gating and dispatch-timeout recovery; `ActionContext` refactor must keep existing `test_actions.py` green.
- **Backward compatibility**: no breaking changes. The dispatch ceiling defaults conservatively high; heartbeat gating is a no-op when systemd watchdog is disabled (`NOTIFY_SOCKET`/`WATCHDOG_USEC` absent).
