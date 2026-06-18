# Proposal: GStreamer capture backend for STT

## Problem

The current STT audio capture path (`parec`) delivers raw PCM to the Vosk
recognizer with no signal conditioning. Noise suppression and AGC are done
entirely in Python (RMS threshold, adaptive RMS, `_apply_input_gain`), which
is coarse and reactive. In noisy environments — fan hum, HVAC, USB power
noise — the recognizer sees a degraded signal, raising false-wake rates and
reducing recognition accuracy.

The existing `audio.webrtc` config block (AGC, NS, AEC, HPF) only sets env
vars consumed by LiveKit room settings; it has never touched the STT capture
path.

## Proposed Solution

Add a second capture backend — `gstreamer` — that replaces `parec` with a
GStreamer pipeline. The pipeline inserts `webrtcdsp` between the microphone
source and the downstream recognizer, providing WebRTC Audio Processing Module
(APM) quality filtering: noise suppression, automatic gain control, and
high-pass filtering. An optional `audiodynamic` compressor can sit downstream
of `webrtcdsp`.

The existing `parec` backend is preserved unchanged. A single config key
(`stt.capture_backend`) switches between them.

### Key design decisions

- **Duck-typing interface**: `GStreamerCapture` exposes `stdout` (pipe read-end
  with `.fileno()`), `poll()`, `terminate()`, and `wait()` — identical to
  `subprocess.Popen`. Zero changes to `stt_gating.py`, `stt_capture.py`, or
  `stt.py`.
- **`pulsesrc` as default source**: same transport as `parec` (proven PipeWire
  PulseAudio compat socket). `pipewiresrc` is available as a config option for
  native-path experiments.
- **Mono output at 16 kHz**: GStreamer performs channel downmix and resampling
  internally. `_downmix_to_mono` becomes a no-op; `_apply_input_gain` remains
  as an optional software trim.
- **AEC excluded**: acoustic echo cancellation requires a `webrtcechoprobe`
  element on the playback path. Since playback is handled by `pw-play`
  subprocesses, wiring AEC would require replacing the entire playback path.
  This is deferred as future work.

## Scope

- **New file** `alexa_custom/stt_gst_capture.py`: `GStreamerCapture` class and
  `start_capture_gst()` factory.
- **`alexa_custom/stt_gating.py`**: one-line dispatch in `start_capture()` to
  branch on `stt.capture_backend`.
- **`alexa_custom/config.py`**: new `GStreamerCaptureConfig` dataclass and
  `audio.gstreamer` config section; new `stt.capture_backend` field.
- **`conf/config.yaml`** (example): document the new keys.
- **`pyproject.toml`**: add `PyGObject` as an optional dependency
  (`[gstreamer]` extra).

## Non-goals

- AEC (future work; requires playback-path echo probe).
- Replacing `pipewiresrc` with `pulsesrc` as the primary (configurable today,
  no forced migration).
- Changing the Vosk recognizer, wake loop, or gating logic.

## Success Criteria

- `stt.capture_backend: gstreamer` starts and streams audio to Vosk without
  changes to any gating/recognition code.
- Noise suppression measurably reduces background noise in RMS readings.
- Switching between `parec` and `gstreamer` in config hot-reloads cleanly.
- All existing STT tests pass with the parec path still as default.
