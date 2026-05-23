# alexa-custom Optimization Report

**Date:** 2026-05-23T13:45:00+00:00  
**Process:** `alexa-client --web` (PID 71862)  
**Uptime at analysis:** ~5m  
**Version:** 0.2.0  

---

## Runtime Snapshot (at analysis time)

| Metric | Value |
|--------|-------|
| CPU% (process) | 123% sustained (multi-core) |
| Hottest thread (TID 71892) | **86.8% CPU** — Vosk STT loop |
| Second thread (TID 71890) | 15.5% CPU — web/broadcast loop |
| Third thread (TID 72422) | 13.4% CPU — aiohttp + audio watcher |
| LiveKit audio threads | 6.3% + multiple tokio-rt-workers |
| RSS | 372 MB |
| Private dirty heap | 331 MB |
| Swap | 0 MB |
| Threads | 19 |
| Open TCP connections | **11** (all from 192.168.2.50 → port 8090) |
| Open file descriptors | 59 |
| CPU temperature (max zone) | 61.0 °C |
| Total write I/O | 141 MB |

---

## Findings & Suggestions

### 1. Double KaldiRecognizer in two-stage mode — HIGH IMPACT

**File:** `alexa_custom/stt.py:430–433, 491–495`

In `_recognition_loop`, two Vosk recognizers run on **every** audio chunk simultaneously:

```python
stage1 = vosk.KaldiRecognizer(model, 16000, _grammar_json(...))  # wake-word grammar
display_rec = vosk.KaldiRecognizer(model, 16000)                  # unrestricted — UI only
```

`display_rec` is only used to populate the "transcribing" partial-text display in the web UI. It is never used for matching; it adds ~40–50% CPU overhead to the already-hot Vosk thread.

**Suggestion:** Drop `display_rec`. Use `stage1.PartialResult()` for the UI partial display instead. The grammar-constrained partial will only show wake-word fragments, which is actually more useful on-screen than noisy unrestricted partials.

```python
# Replace lines 491-495 with:
if stage1.AcceptWaveform(data):
    ...
else:
    if on_stt_event:
        partial = json.loads(stage1.PartialResult()).get("partial", "").strip()
        if partial:
            on_stt_event("transcribing", {"text": partial})
```

And remove the `display_rec` instantiation and re-instantiation (lines 432, 527–529).

**Expected gain:** ~40 percentage points off the Vosk thread (from ~87% → ~50%).

---

### 2. New event loop created on every wake-word dispatch — MEDIUM IMPACT

**File:** `alexa_custom/stt.py:395–406` and `stt.py:619–633`

```python
loop = asyncio.new_event_loop()
loop.run_until_complete(dispatch(...))
loop.close()
```

A brand-new event loop is created and destroyed for every triggered action. This tears down and rebuilds the async executor, task machinery, and internal selectors on each invocation. On a 4-core ARM SoC this is measurably expensive.

**Suggestion:** Create one loop once at `run_stt_worker` startup, reuse it for all dispatches:

```python
# In run_stt_worker, before the while loop:
_dispatch_loop = asyncio.new_event_loop()

# Then in both _single_stage_loop and _wake_detected, replace the loop block with:
_dispatch_loop.run_until_complete(dispatch(...))
# (do NOT close it — reuse it)
```

Close it only when the STT thread exits.

---

### 3. AudioWatcher enforces on every PipeWire event — MEDIUM IMPACT

**File:** `alexa_custom/audio.py:207–209`

```python
while not self._stop.is_set():
    pulse.event_listen(timeout=2.0)
    self._check_and_enforce(pulse)   # called on EVERY event
```

`_check_and_enforce` issues multiple PulseAudio IPC calls (`card_list`, `sink_list`, `source_list`, `server_info`) on every PipeWire event. During active audio streaming PipeWire fires many events per second. This is visible as thread TID 72422 at 13.4% CPU.

**Suggestion:** Debounce with a minimum interval (e.g. 1 second):

```python
last_enforce = 0.0
while not self._stop.is_set():
    pulse.event_listen(timeout=2.0)
    now = time.monotonic()
    if now - last_enforce >= 1.0:
        self._check_and_enforce(pulse)
        last_enforce = now
```

---

### 4. 11 open WebSocket connections from same client — MEDIUM (resource leak)

**Observed:** `ss` shows 11 simultaneous TCP connections from `192.168.2.50` to port 8090.

**File:** `alexa_custom/web.py:542–552`

Dead WebSocket entries are only evicted from `self._clients` when a broadcast fails. If a tab is closed without a clean WebSocket close handshake, the dead connection stays in the set indefinitely. 11 connections from the same IP strongly suggests accumulated stale sockets from browser tab refreshes.

**Suggestion:** Add a periodic prune task that removes already-closed sockets:

```python
async def _prune_clients_loop(self) -> None:
    while True:
        await asyncio.sleep(30)
        self._clients = {ws for ws in self._clients if not ws.closed}
```

Register it alongside `broadcast_task` and `vu_task` in `run()`.

---

### 5. RMS calculated on every chunk even when gated — LOW-MEDIUM IMPACT

**File:** `alexa_custom/stt.py:338–344` and `stt.py:452–453`

```python
if on_stt_event:
    on_stt_event("level", {"mic": _rms_level(data)})   # ← always

if livekit_connected_flag.is_set():
    ...
    continue                                             # ← gated after
```

`_rms_level` allocates a float32 array copy (`astype(np.float32)`) and computes a full sqrt(mean(x²)) on every 4096-byte chunk (~7.8 times/second). The level event is still sent when the call is active (gated state), even though the UI will display "gated" anyway.

**Suggestion:** Check the gate flag before computing RMS:

```python
if livekit_connected_flag.is_set():
    cooldown_until = time.monotonic() + _STT_COOLDOWN
    if on_stt_event:
        on_stt_event("gated", {})
    continue

if on_stt_event:
    on_stt_event("level", {"mic": _rms_level(data)})
```

Also, replace the float32 copy with an in-place view:

```python
def _rms_level(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32, copy=False) ** 2))) / 32768.0
```

Or even simpler using `np.linalg.norm` which avoids the intermediate square array:

```python
def _rms_level(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16)
    if len(samples) == 0:
        return 0.0
    return float(np.linalg.norm(samples)) / (32768.0 * len(samples) ** 0.5)
```

---

### 6. `proc.stdout._rbufsize = 0` — dead code running every 128 ms

**File:** `alexa_custom/stt.py:262`

```python
proc.stdout._rbufsize = 0  # type: ignore[attr-defined]
```

`io.BufferedReader` (Python 3.13) has no `_rbufsize` attribute. This line silently creates a new instance attribute on every loop iteration but has no effect on actual buffering. The `type: ignore` comment suggests it was already known to be fragile.

**Suggestion:** Remove this line entirely.

---

### 7. `asyncio.get_event_loop()` deprecation in ConfigManager — CORRECTNESS

**File:** `alexa_custom/config_manager.py:48`

```python
self._watcher_task = asyncio.get_event_loop().create_task(...)
```

`asyncio.get_event_loop()` is deprecated since Python 3.10 when called outside a running coroutine and will raise `DeprecationWarning` or return the wrong loop. `start_watcher` is always called from an async context.

**Suggestion:**

```python
self._watcher_task = asyncio.get_running_loop().create_task(
    self._poll_loop(p, interval)
)
```

---

### 8. TTS temp files not cleaned up on restart/interrupt — LOW (disk hygiene)

**File:** `alexa_custom/tts.py` (pico2wave call writes to tmp)

`pico2wave` writes to a temp WAV file; if the process is killed mid-TTS the file may not be deleted. Over many restarts (the process restarted at least once during this session: PID changed from 70688 → 71862) temp files can accumulate.

**Suggestion:** Use `tempfile.NamedTemporaryFile(delete=False)` with a try/finally to guarantee cleanup, or `tempfile.mkstemp` + explicit unlink in a finally block.

---

## Priority Summary

| # | Location | Issue | Impact | Effort |
|---|----------|--------|--------|--------|
| 1 | `stt.py:432–529` | Dual KaldiRecognizer in two-stage mode | **High** (−40% CPU) | Low |
| 2 | `stt.py:395, 619` | New event loop per dispatch | **Medium** | Low |
| 3 | `audio.py:207–209` | AudioWatcher runs on every PipeWire event | **Medium** | Low |
| 4 | `web.py` | Stale WebSocket connections accumulate | **Medium** | Low |
| 5 | `stt.py:338, 452` | RMS computed while gated | Low | Low |
| 6 | `stt.py:262` | Dead `_rbufsize` attribute write | Low | Trivial |
| 7 | `config_manager.py:48` | Deprecated `get_event_loop()` | Correctness | Trivial |
| 8 | `tts.py` | TTS temp file cleanup | Low | Low |

Fixes #1–4 alone would reduce sustained CPU from ~123% to an estimated ~70–80%, and bring temperatures down from 61 °C toward 50 °C.
