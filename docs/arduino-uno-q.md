# Audio Libraries and External Programs — Arduino Uno Q

## Platform

- **Board**: Arduino Uno Q (Qualcomm Snapdragon 801, aarch64)
- **OS**: Debian 13 (Trixie)
- **Audio server**: PipeWire 1.4.2 with PulseAudio compatibility socket

## Summary Table

### Input (microphone capture)

| Role | Tool | Type |
|------|------|------|
| Mic capture | `parec` (pulseaudio-utils) | External subprocess |
| Source name discovery | `pactl list sources` | External subprocess |
| Device routing / profile enforcement | `pulsectl` Python library | Python library (wraps libpulse) |
| Call microphone (LiveKit calls only) | `livekit-rtc` SDK | Python library (owns its own PipeWire stream) |

### Output (playback)

| Role | Tool | Type |
|------|------|------|
| All audio playback (TTS, beeps, WAV) | `pw-play` (pipewire-audio-client-libraries) | External subprocess |
| Fallback playback if pw-play absent | `aplay -D pipewire` (alsa-utils) | External subprocess |
| Default sink enforcement | `pulsectl` Python library | Python library (wraps libpulse) |
| Device enumeration only | `sounddevice` / PortAudio | Python library |
| Call speaker (LiveKit calls only) | `livekit-rtc` SDK | Python library (owns its own PipeWire stream) |

---

## Why these choices on this specific platform

### The core constraint: PortAudio has no native PipeWire backend

`sounddevice` and `PyAudio` both wrap PortAudio. On this system, PortAudio was
compiled with only the **ALSA host API** — there is no native PipeWire backend
in any released PortAudio version. PipeWire therefore appears to PortAudio only
through the `alsa-pipewire` plugin, which emulates a virtual ALSA device named
`"pipewire"` (index 6 in `sd.query_devices()`).

This ALSA→PipeWire bridge causes a concrete failure: `sd.play()` + `sd.wait()`
**blocks forever**. PortAudio opens an ALSA stream, writes audio, and then
waits for a stream-completion signal that the ALSA→PipeWire shim never delivers
in the expected form. The result is a hung thread and `_playback_active` stuck
set, which gates the STT microphone indefinitely.

### Why `pw-play` for output

`pw-play` is a **native PipeWire client** — it connects directly to the
PipeWire socket (`/run/user/1000/pipewire-0`) with no ALSA layer in between.
It accepts raw PCM on stdin (`-a` raw mode with `--format`, `--rate`,
`--channels`) and exits cleanly when the stream ends. This gives:

- **Reliable completion**: the subprocess exits when playback finishes; no
  blocking wait required.
- **No ALSA overhead**: avoids the ALSA plugin layer entirely, removing the
  source of the `sd.wait()` hang.
- **Dynamic timeout**: audio duration is known upfront (numpy array length),
  so a per-call subprocess timeout can be computed (`duration × 3 + 5 s`),
  capping worst-case STT gate time.

`aplay -D pipewire` is kept as a fallback for systems where `pw-play` is absent;
it goes through ALSA→PipeWire but is acceptable as a last resort.

### Why `parec` for input

PipeWire exposes a full **PulseAudio compatibility socket** at
`/run/user/1000/pulse/native`. `parec` speaks this protocol natively and can:

- Address a specific source by name
  (`alsa_input.usb-0a12_NewPie_SABINESMICDFU-00.pro-input-0`), not just the
  system default.
- Request exactly `--rate=16000 --channels=2 --format=s16le`, matching Vosk's
  expected input without any resampling in Python.
- Set `--latency-msec=1` to keep the kernel-side buffer tiny, so the capture
  stream starts flowing immediately on PipeWire 1.x.
- Stream raw bytes to stdout, which the STT loop reads with `os.read()` at
  whatever pace Vosk needs — no callback threads, no buffer management.

The alternative (PortAudio/sounddevice capture) has the same ALSA→PipeWire
shim problem on the input side and cannot address PipeWire sources by name.
`pw-record` (native PipeWire) is the fallback, but `parec` is more battle-tested
against the PipeWire PulseAudio compat layer on Debian.

### Why `pulsectl` for routing

`pulsectl` wraps `libpulse` and speaks the same PulseAudio protocol that
PipeWire implements. It is the only Python library that can:

- Set the PipeWire **default sink and source** so that `pw-play` and `parec`
  (which fall back to the system default when no explicit target is given) reach
  the correct NewPie card rather than a built-in or virtual device.
- **Enforce the `pro-audio` profile** on the USB NewPie card at startup and on
  hotplug, which activates the high-channel-count ALSA UCM profile needed for
  the device's aux0/aux1 capture channels.
- React to PipeWire graph events (`AudioWatcher` daemon thread) and re-enforce
  routing if it changes (e.g. after a LiveKit session alters the graph).

### Why `sounddevice` is kept but not used for I/O

`sounddevice` is still imported for two narrow uses:

1. **Device listing** (`sd.query_devices()`) — enumerates all ALSA/PipeWire
   devices visible to PortAudio, used by `alexa-audio --list` and the
   speakerphone diagnostic.
2. **`speakerphone` loopback** (`sd.Stream`) — a developer utility that mirrors
   mic input to speaker output in real time; acceptable to use PortAudio here
   because it runs in isolation with no STT gate interaction.

It is explicitly **not used** for any production audio I/O path.

### Why not PyAudio

PyAudio wraps the same PortAudio library as `sounddevice` and has identical
ALSA-only backend constraints on this platform. It additionally lacks the
numpy array integration that makes `sounddevice` convenient for device queries.
There is no reason to add it.

### Why not JACK

PipeWire exposes a JACK compatibility layer, but it requires explicit JACK
session management (`jackd` or `pw-jack` wrapper) and adds configuration
complexity with no benefit over the native PipeWire clients (`pw-play`,
`parec`) already available.
