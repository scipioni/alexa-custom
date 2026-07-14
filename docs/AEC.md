# Acoustic Echo Cancellation (AEC)

This document covers system-level microphone preprocessing on the Arduino Uno Q target board
(PipeWire 1.4.2, Debian Trixie) and how to integrate it with alexa-custom.

The goal is to remove speaker output from the microphone signal **before** it reaches the STT
pipeline — preventing false wake-word triggers from TTS playback and reducing room echo.

---

## Why AEC matters for wake-word detection

When alexa-custom plays a TTS response, the speaker output is picked up by the microphone and
fed back into the STT pipeline. Without AEC this can cause:

- False wake-word triggers on the tail end of TTS playback.
- Elevated noise floor degrading recognition accuracy in reverberant rooms.

alexa-custom has a software gate (`post_playback_ms`) that blanks the STT input during and
briefly after playback, but it cannot suppress echo that bleeds past the gate or room
reverberation from walls and furniture.

---

## Option 1 — PipeWire WebRTC AEC (recommended)

PipeWire ships `libpipewire-module-echo-cancel` with a WebRTC-based AEC backend. It creates a
pair of virtual sink + source nodes: audio routed to the virtual sink is used as the reference
signal; the virtual source exposes the echo-cancelled microphone.

### Prerequisites

Verify the required shared objects are present:

```bash
find /usr/lib -name "libspa-aec-webrtc.so" -o -name "libpipewire-module-echo-cancel.so"
```

Both files must exist. On Debian Trixie they are installed by `pipewire` and `libspa-0.2-modules`.

### Configuration

Create a PipeWire drop-in (user-level, no root required):

```bash
mkdir -p ~/.config/pipewire/pipewire.conf.d
```

```bash
cat > ~/.config/pipewire/pipewire.conf.d/99-echo-cancel.conf << 'EOF'
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name  = aec/libspa-aec-webrtc
      node.latency  = 1024/16000
      source.props = { node.name = "echo-cancel-source" }
      sink.props   = { node.name = "echo-cancel-sink" }
      aec.args = {
        # Cuts frequencies below ~80 Hz (rumble, handling noise)
        webrtc.high_pass_filter    = true
        # Spectral subtraction of stationary background noise (fans, HVAC)
        webrtc.noise_suppression   = true
        # VAD — prevents AEC from adapting during silence; required by gain_control
        webrtc.voice_detection     = true
        # AGC — normalises mic level regardless of speaker distance or room size
        webrtc.gain_control        = true
        # Extends echo tail estimation from ~128 ms to ~500 ms for reverberant rooms
        webrtc.extended_filter     = true
      }
    }
  }
]
EOF
```

Apply by restarting PipeWire:

```bash
systemctl --user restart pipewire pipewire-pulse wireplumber
```

> **Note on `libpipewire-module-switch-on-connect`**: this module is NOT available on
> PipeWire 1.4.2 on the board — the `nofail` flag does not suppress the crash on this build.
> Do not add it to the same drop-in. `task audio:setup` actively removes any stale
> `99-switch-on-connect.conf` to prevent this.

### Verify the virtual nodes appeared

```bash
pactl list sources | grep -E "Name:|Description:" | grep -i "echo"
```

Expected output:

```
Name: echo-cancel-source
    Description: Echo-cancelled Microphone
```

```bash
pactl list sinks | grep -E "Name:|Description:" | grep -i "echo"
```

Expected output:

```
Name: echo-cancel-sink
    Description: Echo-cancelled Playback
```

### Route system output through the AEC sink

For AEC to work, **both** the reference signal (speaker) and the microphone must pass through
the module. Set the AEC sink as the default output:

```bash
pactl set-default-sink echo-cancel-sink
```

Or use `wpctl`:

```bash
wpctl set-default @DEFAULT_AUDIO_SINK@ "$(wpctl status | grep echo-cancel-sink | awk '{print $1}')"
```

The module automatically links the real physical sink downstream.

### Verify with a recording

Record 5 seconds while playing audio through the speaker — the playback should be largely
absent from the recorded signal:

```bash
# Find the exact source name
pactl list sources | grep "Name:" | grep echo

# Play a test tone and record simultaneously
pw-play /usr/share/sounds/alsa/Front_Center.wav &
parec --rate=16000 --channels=1 --format=s16le --latency-msec=1 \
  --device=echo-cancel-source \
  | sox -t raw -r 16000 -e signed -b 16 -c 1 - /tmp/aec-test.wav trim 0 5

# Listen to the result
pw-play /tmp/aec-test.wav
```

If AEC is working the speaker tone will be suppressed in the recording. A faint residual is
normal; complete silence is ideal.

### Integrate with alexa-custom

Both `input_device` and `output_device` must be set for AEC to work end-to-end:

- `input_device` — tells `parec` to read from the echo-cancelled virtual microphone.
- `output_device` — controls where TTS playback goes. The AEC module needs to hear the
  speaker output as its reference signal; if playback bypasses `echo-cancel-sink`, the
  module has nothing to cancel against.

#### Recommended configuration

```yaml
audio:
  input_device: "echo-cancel-source"   # parec reads from the AEC virtual mic
  output_device: "pipewire"            # let WirePlumber route to the default sink
```

Set `echo-cancel-sink` as the system default sink once at startup (see below) and leave
`output_device: pipewire` in the config. This avoids a known limitation: `enforce_audio_state`
in `audio_hw.py` only recognises `"pipewire"` and `"default"` as virtual sinks — passing
`"echo-cancel-sink"` directly causes it to call `find_alexa_card` on a virtual node, get
`None`, and log a spurious `disconnected` warning on every AudioWatcher cycle.

#### Make echo-cancel-sink the default at boot

Add a `pactl` call to the existing `alsa-pcm-unmute.service` (installed by `task audio:setup`),
or create a small drop-in that runs after PipeWire is ready:

```bash
# One-shot — run once per session after pipewire starts
pactl set-default-sink echo-cancel-sink
```

Or persist it via WirePlumber metadata so it survives restarts:

```bash
wpctl set-default $(wpctl status | awk '/echo-cancel-sink/{print $2}' | tr -d '.')
```

Hot-reload applies `input_device` / `output_device` changes within ~4 seconds with no
daemon restart needed.

### WebRTC AEC flags explained

Each `aec.args` flag maps to a component of the WebRTC AudioProcessing Module (APM) — the
same DSP stack used inside Chrome and all WebRTC calls.

| Flag | What it does | Why it matters for wake-word detection |
|------|-------------|----------------------------------------|
| `high_pass_filter` | First-order IIR filter that attenuates everything below ~80 Hz | Removes low-frequency rumble (AC units, traffic, mic cable vibration). Voice energy starts at ~200 Hz so nothing useful is lost. Cheap — no downside to leaving on. |
| `noise_suppression` | Estimates a stationary noise floor per-frequency-bin and applies spectral subtraction | Lifts Vosk confidence scores on clean speech by reducing the noise that competes with formants. Most effective on constant sources (fans, hum). |
| `voice_detection` | Built-in VAD that classifies each 10 ms frame as speech or non-speech | Prevents AEC and AGC from adapting during silence or noise bursts — keeps their internal state stable between utterances. Essentially a prerequisite for `gain_control` to work correctly. |
| `gain_control` | AGC — measures long-term RMS and applies a compensating gain to keep voice at a target level | Biggest practical benefit: speaking from 2 m away produces the same input level as speaking from 0.5 m. Removes the need to hand-tune `input_gain` in `conf/config.yaml`. |
| `extended_filter` | Extends the AEC tail from ~128 ms to ~500 ms by using a longer adaptive filter | Handles rooms where speaker output reflects off walls and arrives at the mic >100 ms later. On the NewPie (speaker and mic in the same unit) this is less critical, but useful in large or reflective rooms. |

All five are safe to leave enabled simultaneously. CPU overhead on the Snapdragon 801 is
negligible — the APM processes 10 ms frames at 16 kHz, well within the board's headroom.

---

## Option 2 — RNNoise (neural noise suppression)

RNNoise runs a recurrent neural network to suppress stationary and non-stationary background
noise. It does **not** perform echo cancellation (it has no reference signal), but it is very
effective at reducing fan noise, HVAC hum, and keyboard/room ambience.

### Prerequisites

RNNoise requires the LADSPA wrapper plugin `librnnoise_ladspa.so`. The base `librnnoise`
library is present on this system but the LADSPA wrapper is a separate package:

- **Arch Linux (dev machine)**: `yay -S noise-suppression-for-voice`
- **Debian Trixie (board)**: `sudo apt install pipewire-plugin-rnnoise`

Verify after install:

```bash
find /usr/lib/ladspa -name "librnnoise_ladspa*"
```

### Configuration

A stock example config ships with PipeWire at
`/usr/share/pipewire/filter-chain/source-rnnoise.conf`. Copy and activate it:

```bash
mkdir -p ~/.config/pipewire/filter-chain.conf.d
cp /usr/share/pipewire/filter-chain/source-rnnoise.conf \
   ~/.config/pipewire/filter-chain.conf.d/
systemctl --user restart pipewire pipewire-pulse wireplumber
```

The virtual source will appear as `effect_output.rnnoise`. Point alexa-custom at it:

```yaml
audio:
  input_device: "rnnoise"   # substring match
```

### Combining with AEC

RNNoise and the WebRTC AEC can be chained: run RNNoise first to suppress background noise,
then feed its output into the AEC module as the microphone signal. This requires a custom
filter-chain config that links the nodes explicitly — out of scope for this document.

In practice, **AEC alone covers both echo and noise suppression** via `webrtc.noise_suppression`
and is simpler to set up. Add RNNoise only if AEC noise suppression is insufficient.

---

## Troubleshooting

### Virtual source does not appear after restart

Check the PipeWire journal for module load errors:

```bash
journalctl --user -u pipewire -n 50 --no-pager | grep -i "echo\|error\|fail"
```

Common causes:
- `libspa-aec-webrtc.so` not found — install `libspa-0.2-modules` (Debian) or `pipewire` (Arch).
- Syntax error in the `.conf` file — validate with `pipewire --version` and check the log.

### AEC source exists but no echo suppression

The module only cancels echo if audio is **routed through `echo-cancel-sink`**. If applications
play directly to the hardware sink, the AEC module never sees the reference signal.

```bash
# Confirm default sink is the AEC sink
pactl info | grep "Default Sink"
```

If the default sink is the hardware device rather than `echo-cancel-sink`, set it:

```bash
pactl set-default-sink echo-cancel-sink
```

### output_device: "echo-cancel-sink" logs spurious "disconnected" warnings

`enforce_audio_state` in `audio_hw.py` calls `find_alexa_card` to resolve the output device
to an ALSA card. Virtual PipeWire nodes (including `echo-cancel-sink`) have no backing ALSA
card, so it returns `None` and logs a `disconnected` warning on every AudioWatcher cycle.

**Fix**: keep `output_device: pipewire` in `conf/config.yaml` and set `echo-cancel-sink` as
the system default sink at boot instead (see "Integrate with alexa-custom" above).

### PCM reset after pulsectl interaction

Opening any `pulsectl.Pulse()` connection causes pipewire-pulse to re-initialize the ALSA
device, resetting the NewPie hardware PCM to 0%. This happens independently of AEC.
See `CLAUDE.md` section 5 ("pulsectl Triggers PCM Reset") and the `_restore_hw_pcm()` call
pattern in `alexa_custom/audio.py`.

### alexa-custom does not pick up the AEC source

`resolve_capture_source` in `stt_gating.py` does a case-insensitive substring match against
`pactl list sources`. If the source name changed (e.g. PipeWire assigned a numeric suffix),
update `input_device` in `conf/config.yaml` to match the new substring.

```bash
pactl list sources | grep "Name:"
```

---

## Quick-reference commands

| Task | Command |
|------|---------|
| List all sources | `pactl list sources \| grep "Name:"` |
| List all sinks | `pactl list sinks \| grep "Name:"` |
| Record from AEC source (5 s) | `parec --rate=16000 --channels=1 --format=s16le --latency-msec=1 --device=echo-cancel-source \| sox -t raw -r 16000 -e signed -b 16 -c 1 - /tmp/test.wav trim 0 5` |
| Set AEC sink as default output | `pactl set-default-sink echo-cancel-sink` |
| Confirm current default sink | `pactl info \| grep "Default Sink"` |
| Check PipeWire errors | `journalctl --user -u pipewire -n 50 --no-pager` |
| Restore NewPie PCM after pulsectl | `amixer -c 0 sset PCM 100%` |
| Reload alexa-custom config | Edit `conf/config.yaml` — hot-reload in ~4 s |
