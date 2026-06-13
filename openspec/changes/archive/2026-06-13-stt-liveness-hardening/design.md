## Context

The daemon runs three independent async/threading contexts:

1. **Main async loop** (`client.py`) — LiveKit session, MQTT, hot-reload callbacks, and the systemd watchdog ping (`sd_notify("WATCHDOG=1")` every 10s, gated by `should_use_watchdog()`).
2. **STT daemon thread** (`stt.py`) — owns a *dedicated* event loop created at `run_stt_worker` (`_dispatch_loop = asyncio.new_event_loop()`). Each detected turn runs synchronously via `_dispatch_loop.run_until_complete(dispatch(...))` at 6 call sites.
3. **Web loop** (`web.py`) — its own `new_event_loop()`.

A thread→main-loop bridge already exists and is used for MQTT (`asyncio.run_coroutine_threadsafe(coro, loop)` at `client.py:768/778`), so cross-context coroutine scheduling is an established pattern in this codebase.

Two failure modes are currently unhandled:
- **Alive-but-hung STT thread**: `run_until_complete(dispatch(...))` has no upper bound. A wedged `listen_fn`, stalled LiveKit connect, or slow LLM freezes recognition. The existing `stt-thread-watchdog` capability only checks `is_alive()`, which stays `True` for a hung thread. The systemd ping lives on the *main* loop, which keeps running — so systemd never restarts the deaf process.
- **Deaf-during-shutdown**: `time.sleep(2)` in backend-reload error handlers ignores `stop_event` for up to 2s.

`dispatch()` / `_run_action()` thread ~10 positional/keyword args through every call. Adding a deadline or cancellation token today means editing both signatures plus all 6 call sites.

## Goals / Non-Goals

**Goals:**
- A hung STT thread results in an automatic systemd restart within the watchdog window.
- A single turn cannot block recognition beyond a configurable ceiling.
- Shutdown is honored promptly even mid-reload-error.
- Make the dispatch argument surface extensible so future deadline/cancellation plumbing is a one-field change.

**Non-Goals:**
- Moving dispatch off the STT thread. Synchronous on-thread execution is intentional: it guarantees no recognition occurs while the device is speaking or awaiting a follow-up. We bound and observe the blocking, not eliminate it.
- Replacing or modifying the existing `stt-thread-watchdog` (thread-death) capability. Hang detection is complementary.
- Changing the systemd unit file's `WatchdogSec` value (assumed already set for `Type=notify`).

## Decisions

### 1. Do the `ActionContext` refactor first
Collapse the threaded args of `dispatch()` / `_run_action()` into a single frozen-ish dataclass:

```python
@dataclass
class ActionContext:
    telegram_client: TelegramClient
    livekit_connect_fn: Callable[[], Awaitable[None]] | None
    livekit_connected: bool
    listen_fn: Callable[[float], Awaitable[str]] | None
    mqtt_client: MQTTClient | None
    on_stt_event: Callable[[str, dict], None] | None
    actions_config: ActionsConfig | None
```

`dispatch(trigger, ctx, *, wake_word=None, transcript=None)`. The 6 call sites in `stt.py` build one `ctx` (most fields are loop-invariant for a given worker run) and pass it down. **Rationale**: decision #2 (timeout) and any later cancellation token become a single added field rather than a 6-site edit. **Alternative considered**: skip the refactor and just wrap dispatch in `wait_for`. Rejected — the timeout needs no new args, but the follow-up work (propagating a cancel signal into `listen_fn`) would, and doing the refactor now is cheap and behavior-preserving (existing `test_actions.py` is the safety net).

### 2. Bound dispatch with `asyncio.wait_for`
Wrap each `run_until_complete(dispatch(...))` as `run_until_complete(asyncio.wait_for(dispatch(...), timeout=ceiling))`. On `asyncio.TimeoutError`: log, reset the loop's recognition state (the same reset path used after a normal turn), and continue. **Rationale**: `wait_for` cancels the coroutine on timeout, unwinding awaited sub-tasks. **Trade-off**: cancellation only takes effect at `await` points — a sub-call blocked in synchronous C code (unlikely on this path, which is all awaitable network/TTS I/O) won't be interrupted. Acceptable given the path is async I/O end to end. **Alternative**: a separate timer thread that force-kills — rejected as far more invasive than co-operative cancellation.

### 3. Heartbeat as a plain monotonic value, gating the ping
The STT loop writes `heartbeat[0] = time.monotonic()` (a shared single-element list or a small holder object) once per iteration. The main loop, before sending `WATCHDOG=1`, checks `time.monotonic() - heartbeat[0] < freshness`. **Rationale**: a plain monotonic write/read needs no lock (atomic enough for a liveness check; we only care about staleness on the order of seconds). **Constraint**: `freshness < WatchdogSec` so a stalled heartbeat actually lets the timer expire. With the existing 10s ping interval and a typical `WatchdogSec=30`, a freshness of ~20s gives margin. **Alternative considered**: a `threading.Event` toggled each loop — rejected, monotonic timestamp directly expresses "how stale" which is what the gate needs.

### 4. `stop_event.wait(2)` instead of `time.sleep(2)`
Mechanical substitution in the reload-error handlers. `stop_event.wait(timeout)` returns immediately when set. No design tension.

## Risks / Trade-offs

- **Timeout ceiling too low kills legitimate long turns** → default conservatively high (e.g. 60s, covering LiveKit connect backoff and long LLM replies); make it `recognition.dispatch_timeout` so it is tunable per deployment.
- **Heartbeat freshness mis-tuned vs `WatchdogSec`** → document the relationship (`freshness < WatchdogSec - ping_interval`) and assert/log the values at startup; if the systemd watchdog is disabled the gate is inert.
- **`wait_for` cancellation leaves partial side effects** (e.g. half-connected LiveKit) → the timeout path runs the same state-reset used after a normal turn; LiveKit's own reconnect/no-op-if-connected logic (per `action-dispatch` spec) tolerates a retry.
- **ActionContext refactor regresses a handler** → covered by existing `test_actions.py`; the change is purely structural (same values, new container).
- **Heartbeat read without a lock races** → tolerable: worst case the main loop reads a value one iteration stale, which only shifts the staleness decision by a few ms — far below the seconds-scale threshold.

## Migration Plan

1. Land `ActionContext` (behavior-preserving); confirm `test_actions.py` green.
2. Add `recognition.dispatch_timeout` config key with default; wrap dispatch in `wait_for`.
3. Add heartbeat holder + stamp in the STT loop; gate the `WATCHDOG=1` ping in `client.py`.
4. Replace `time.sleep(2)` → `stop_event.wait(2)` in reload-error handlers.

Rollback: each step is independent and revertible; the heartbeat gate is inert when the systemd watchdog is disabled, so it can ship dark.

## Open Questions

- Final default value for `recognition.dispatch_timeout` — 60s proposed; confirm against the LiveKit connect backoff ceiling (30s per `action-dispatch` spec) plus longest expected LLM reply.
- Should a dispatch timeout also emit a WebSocket event (like `stt_dead`) for dashboard visibility? Leaning yes, but it can be a follow-up rather than blocking this change.
