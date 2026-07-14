# Tasks: GStreamer capture backend for STT

## Config

- [x] Add `GStreamerCaptureConfig` dataclass to `alexa_custom/config.py`
- [x] Add `gstreamer: GStreamerCaptureConfig` field to `AudioConfig`
- [x] Add `capture_backend: str = "parec"` field to `STTConfig`
- [x] Add YAML parsing for `audio.gstreamer` block (follow `webrtc` pattern)
- [x] Add YAML parsing for `stt.capture_backend`
- [x] Document new keys in `conf/config.yaml` with comments

## Core implementation

- [x] Create `alexa_custom/stt_gst_capture.py`:
  - [x] `_build_pipeline_string(source_name, config)` — builds the
        `gst-parse-launch`-style pipeline string from `GStreamerCaptureConfig`
  - [x] `GStreamerCapture` class:
    - [x] `__init__`: `os.pipe()`, `Gst.parse_launch()`, `fdsink fd=write_fd`,
          set pipeline to PLAYING, start bus-watch thread
    - [x] `stdout` property: `os.fdopen(read_fd, "rb", buffering=0)`
    - [x] `poll()`: returns `None` while alive, `1` when `_dead`
    - [x] `terminate()`: `pipeline.set_state(Gst.State.NULL)`, close write-end fd
    - [x] `wait(timeout)`: join bus-watch thread
    - [x] bus-watch thread: loop `bus.timed_pop_filtered(100ms, ERROR|EOS)`,
          set `_dead=True` and close write-end on any message
  - [x] `start_capture_gst(source_name, config)` factory function

## Dispatch

- [x] In `alexa_custom/stt_gating.py`, rename current `start_capture` body to
      `_start_capture_parec`
- [x] Add `config` parameter to `start_capture()` (default `None`)
- [x] Add dispatch: if `config.stt.capture_backend == "gstreamer"` call
      `start_capture_gst`
- [x] Update the `start_capture()` call in `alexa_custom/stt.py` to pass
      `config=current_config`

## Dependency

- [x] Add `[gstreamer]` optional extra to `pyproject.toml`:
      `PyGObject>=3.46`

## Verification

- [ ] Manual test: set `stt.capture_backend: gstreamer` in `conf/config.yaml`,
      run `task run`, speak a wake word — confirm recognition works
- [ ] Manual test: switch back to `parec` — confirm hot-reload restarts cleanly
      with no crash
- [ ] Manual test: enable `noise_suppression: true`, compare RMS readings in
      the web dashboard with fan/HVAC noise present
- [ ] Manual test: set `capture_backend: gstreamer` with `pipewiresrc` source —
      confirm audio flows (experimental)
- [ ] Run `task test` — all existing STT tests pass (parec path is still default)
