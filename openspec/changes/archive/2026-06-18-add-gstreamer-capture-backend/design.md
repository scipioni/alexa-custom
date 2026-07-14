# Design: GStreamer capture backend for STT

## Architecture Overview

```
                     ┌─────────────────────────────────────┐
                     │         GStreamerCapture             │
                     │                                      │
  NewPie mic         │  pulsesrc  ──  webrtcdsp  ──  fdsink│──▶ pipe read-end
  (PipeWire graph)──▶│  [pipewiresrc]  [audiodynamic]       │    (proc.stdout)
                     │                                      │
                     └─────────────────────────────────────┘
                                                │
                              stt_gating._iter_gated_audio()
                              (no changes — same pipe interface)
                                                │
                                           Vosk / sherpa-onnx
```

The `parec` path is unchanged:

```
  parec subprocess ──▶ proc.stdout (pipe)
                              │
                    stt_gating._iter_gated_audio()
```

Both paths converge at the same `_iter_gated_audio` call in `stt.py`.

---

## GStreamer Pipeline

### Pipeline string (constructed at runtime)

```
pulsesrc device=<source_name> latency-time=10000 buffer-time=20000
  ! audio/x-raw,rate=16000,channels=1
  ! audioconvert
  ! webrtcdsp
      noise-suppression=<bool>
      noise-suppression-level=<0-3>
      gain-control=<bool>
      target-level-dbfs=<int>
      compression-gain-db=<int>
      high-pass-filter=<bool>
      echo-cancel=false
      voice-detection=false
  [! audiodynamic mode=compressor threshold=<f> ratio=<f> characteristics=soft-knee]
  ! audioconvert
  ! audio/x-raw,format=S16LE,rate=16000,channels=1
  ! fdsink fd=<write_fd> sync=false
```

- `device=<source_name>` is omitted when `source_name` is None (use PipeWire default).
- `pipewiresrc` replaces `pulsesrc` when `audio.gstreamer.source == "pipewiresrc"`. Its
  property for the device is `target-object` instead of `device`.
- `audiodynamic` block is only inserted when `audio.gstreamer.compressor == true`.
- `sync=false` on `fdsink` prevents GStreamer from throttling to real-time clock,
  letting the OS pipe buffer absorb timing jitter.

### Why `fdsink` into `os.pipe()`

`_read_with_timeout` uses `select.select` + `os.read` on the raw fd — identical
behavior to a `subprocess.Popen` stdout pipe. `_drain_pipe` sets `O_NONBLOCK` on
the same fd. Both work without modification.

---

## `GStreamerCapture` class

```python
class GStreamerCapture:
    stdout: RawIO         # os.fdopen(pipe_read_fd, "rb", buffering=0)

    def poll(self) -> int | None:
        # Returns None while pipeline is PLAYING
        # Returns 1 when bus signals ERROR or EOS (_dead flag set by bus callback)

    def terminate(self) -> None:
        # pipeline.set_state(Gst.State.NULL)
        # closes write-end fd → EOF on read-end → _drain_pipe unblocks cleanly

    def wait(self, timeout: float | None = None) -> int:
        # joins the bus-watch thread (bounded by timeout)
        # returns 1
```

### Bus-watch thread

A daemon thread calls `bus.timed_pop_filtered(100_ms, ERROR | EOS)` in a loop.
On any error or EOS it sets `_dead = True` and closes the write-end fd.
`poll()` returns `1` (non-None), triggering the restart logic in `stt.py:716-722`
exactly as if `parec` had exited.

---

## Dispatch in `start_capture()`

Current signature in `stt_gating.py`:

```python
def start_capture(source: str | None, channels: int = 1) -> subprocess.Popen:
```

Change to:

```python
def start_capture(
    source: str | None,
    channels: int = 1,
    config: ActionsConfig | None = None,
) -> subprocess.Popen:          # return type unchanged (duck-typed)
    if config is not None and config.stt.capture_backend == "gstreamer":
        from alexa_custom.stt_gst_capture import start_capture_gst
        return start_capture_gst(source, config.audio.gstreamer)
    return _start_capture_parec(source, channels)   # current body, renamed
```

All callers in `stt.py` already have `current_config` in scope; they pass it
through. No other callers exist outside of tests, which mock `start_capture`.

---

## Config dataclasses (`config.py`)

```python
@dataclass
class GStreamerCaptureConfig:
    source: str = "pulsesrc"               # pulsesrc | pipewiresrc
    noise_suppression: bool = True
    noise_suppression_level: int = 2       # 0=mild 1=moderate 2=high 3=very-high
    agc: bool = True
    agc_target_level_dbfs: int = -18       # dBFS target (-18 to -6)
    agc_compression_gain_db: int = 9       # max makeup gain dB
    high_pass_filter: bool = True
    compressor: bool = False               # audiodynamic compressor stage
    compressor_threshold: float = 0.1      # normalized 0.0–1.0
    compressor_ratio: float = 3.0
```

Added to `AudioConfig`:

```python
@dataclass
class AudioConfig:
    ...
    gstreamer: GStreamerCaptureConfig = field(default_factory=GStreamerCaptureConfig)
```

Added to `STTConfig` (or flat STT config, wherever `capture_backend` lives):

```python
    capture_backend: str = "parec"         # parec | gstreamer
```

YAML parsing follows the same `raw.get(...)` pattern as `webrtc`.

---

## Error handling and restart

| Condition | Behaviour |
|-----------|-----------|
| GStreamer bus ERROR | `_dead=True`, write-end closed → `poll()` returns 1 → `stt.py` restarts in 2 s |
| GStreamer bus EOS | same as ERROR |
| `terminate()` called | `pipeline.set_state(NULL)` → clean stop |
| `webrtcdsp` not found at runtime | `Gst.parse_launch` raises → caught by `stt.py` outer try/except → logs error, restarts |
| `gi` / GStreamer not installed | `ImportError` in `start_capture_gst` → logs clear message, falls back NOT attempted (explicit failure preferred over silent fallback) |

---

## Dependency

`PyGObject` (`gi`) is already present if GStreamer Python bindings are
installed. Add as optional dep:

```toml
[project.optional-dependencies]
gstreamer = ["PyGObject>=3.46"]
```

The import of `gi.repository.Gst` is guarded inside `stt_gst_capture.py` and
only executed when `capture_backend == "gstreamer"`, so the absence of
`PyGObject` has no effect on the default parec path.

---

## Alternatives Considered

- **`appsink` callback + queue**: pushes buffers via GLib signal into a
  `queue.Queue`, wrapped with a fake file-like object. More complex and
  introduces a Python-side buffer. Rejected in favour of `fdsink` + OS pipe,
  which reuses the exact same fd-based read path already in place.
- **`pipewiresrc` as default**: lower latency, but unproven with `webrtcdsp`
  negotiation on this board. `pulsesrc` mirrors the proven `parec` transport.
  `pipewiresrc` remains a config option for experimentation.
- **Software NS in Python (noisereduce / RNNoise)**: higher latency (block
  processing), extra dependency, CPU cost on the Snapdragon 801. WebRTC APM
  via `webrtcdsp` runs in real-time in C++.
