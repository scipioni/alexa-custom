## Context

Volume is currently managed at the PipeWire layer via `wpctl set-volume @DEFAULT_AUDIO_SINK@`. All playback functions (`_play_array`, `_play_raw`, Piper streaming) send audio at 0 dBFS and rely on PipeWire's per-sink software volume for attenuation. This works on the dev system (Arch Linux, modern WirePlumber) where the USB NewPie is reliably the default sink, but fails on the Arduino Uno Q (Debian Trixie, PipeWire 1.4.2) where late USB discovery means WirePlumber never sets NewPie as default.

The current architecture has three independent volume layers:

| Layer | Mechanism | Reliability on board |
|-------|-----------|---------------------|
| Application (digital) | `_OUTPUT_VOLUME` stored but **never applied** to samples | N/A — not used |
| PipeWire (sink) | `wpctl set-volume @DEFAULT_AUDIO_SINK@` | ❌ — default sink is often HDMI |
| ALSA (hardware) | `amixer PCM` via `_restore_hw_pcm()` after every operation | ✓ — always forced to 100% |

The fix moves volume from the PipeWire layer to the application layer, making it independent of system audio routing.

## Goals / Non-Goals

**Goals:**
- Volume slider (0-100%) works identically on Arch dev system and Arduino Uno Q
- Zero config changes — same `config.yaml` works on both
- No new dependencies
- Minimal lines changed (< 10)

**Non-Goals:**
- System-wide volume control for non-alexa audio sources
- WirePlumber routing fixes or workarounds
- Audio quality optimization (digital gain at low volumes may reduce effective bit depth, acceptable for voice assistant)

## Decisions

**Decision 1: Digital gain in `_play_array` / `_play_raw` instead of `pw-play --volume`**
- `pw-play --volume` works but only applies to the WAV file path; Piper streaming bypasses it entirely via `paplay --stdin`
- Digital gain in the numpy domain covers ALL playback paths with one change
- Minimal: 1 line added in `_play_array`, 1 line added in `_play_raw`

**Decision 2: Force PipeWire sink to 100% in `set_output_volume`**
- If both digital gain AND wpctl attenuation were active, volume would be squared (e.g. 0.5 × 0.5 = 0.25)
- Setting wpctl to 1.0 eliminates double-attenuation on dev system
- On the board where wpctl doesn't affect NewPie, this is a no-op

**Decision 3: Retain `_restore_hw_pcm()` after wpctl call**
- The PCM reset bug (AGENTS.md §5) is independent of volume control — `wpctl` still triggers the reset even at unity
- `_restore_hw_pcm()` after every wpctl call remains necessary

**Decision 4: Scale at float32 precision, before int16 conversion**
- Applying gain AFTER int16 conversion would cause quantization artifacts
- Multiplying the float32 array before `* 32767` preserves precision

## Risks / Trade-offs

- **Double attenuation if gain added before wpctl removed**: Mitigated by always setting wpctl to 1.0 in the same change
- **PCM reset race**: `wpctl set-volume` triggers WirePlumber ALSA re-init, which resets PCM to 0%. `_restore_hw_pcm()` runs right after, but if WirePlumber's re-init is asynchronous, there's a brief window where PCM is 0%. Current polling in `alsa-pcm-unmute.service` handles this. No change to existing mitigation.
- **Lower effective bit depth at low volumes**: At 10% volume, signal uses ~13 bits instead of 16. Acceptable for voice/speech. No change from current behavior where wpctl applies same gain at PipeWire level.
- **`_restore_hw_pcm()` missing after `with pulsectl.Pulse()` context closes**: Pre-existing bug in `actions.py:handle_set_volume` and `client.py` startup. Out of scope for this change but worth noting.
