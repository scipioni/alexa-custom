#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
import threading
import time
import logging
from typing import Callable
import numpy as np
import pulsectl

# Resolved once at import time; None if the tool is absent (aplay fallback used).
_PW_PLAY: str | None = shutil.which("pw-play")

logger = logging.getLogger(__name__)

# Global flag to signal that playback is active and STT should ignore input
_playback_active = threading.Event()

# Serializes all internal playback (TTS, tones, beeps, WAVs) so they don't overlap,
# and so the STT-gating flag is owned by exactly one playback at a time.
_audio_lock = threading.Lock()

# Hold the STT-gating flag this long after the playback subprocess returns, to let
# PipeWire/ALSA buffers drain through hardware and the acoustic echo decay before
# capture resumes. Override via env AUDIO_POST_PLAYBACK_MS.
_POST_PLAYBACK_MS = int(os.environ.get("AUDIO_POST_PLAYBACK_MS", "100"))

# Prepend this much silence to short tones/beeps so the PipeWire sink finishes its
# cold-start (stream open + device wake) before the audible part begins. Override
# via env AUDIO_TONE_PREROLL_MS.
_TONE_PREROLL_MS = int(os.environ.get("AUDIO_TONE_PREROLL_MS", "300"))


def set_stt_gated_flag(flag: threading.Event):
    """Link an external event (like the STT gating flag) to our playback state."""
    global _playback_active
    _playback_active = flag


def is_playback_active() -> bool:
    """Check if any internal audio playback is currently in progress."""
    return _playback_active.is_set()


# Sample rates by connection type
_SAMPLERATE = {"usb": 48000, "bluetooth": 16000}


def find_pipewire_device():
    """Return the sounddevice index for the PipeWire ALSA device."""
    import sounddevice as sd
    return next(
        (i for i, d in enumerate(sd.query_devices()) if d["name"] == "pipewire"),
        None,
    )


_pw_device_resolved = False
_pw_device_index: int | None = None


def get_pipewire_device() -> int | None:
    """Cached lookup of the PortAudio index of the PipeWire ALSA device.

    sd.query_devices() is mildly expensive (PortAudio re-scans the host APIs).
    The PipeWire virtual device's index is stable for the lifetime of the
    process, so resolve once and reuse for every beep / tone / TTS frame.
    """
    global _pw_device_resolved, _pw_device_index
    if not _pw_device_resolved:
        _pw_device_index = find_pipewire_device()
        _pw_device_resolved = True
    return _pw_device_index


def invalidate_pipewire_device_cache() -> None:
    """Clear the cached PortAudio device index (call on hardware status change)."""
    global _pw_device_resolved, _pw_device_index
    _pw_device_resolved = False
    _pw_device_index = None


def resolve_device(name_or_index: str) -> int:
    """Resolve a device name substring or numeric index string to a sounddevice index."""
    import sounddevice as sd
    if name_or_index.strip().lstrip("-").isdigit():
        return int(name_or_index)
    needle = name_or_index.lower()
    for i, d in enumerate(sd.query_devices()):
        if needle in d["name"].lower():
            return i
    raise RuntimeError(
        f"Audio device not found: {name_or_index!r} — run 'alexa-audio --list' to see available devices"
    )


def device_from_env(key: str) -> int | None:
    """Return the sounddevice index for INPUT_DEVICE or OUTPUT_DEVICE, or None if unset."""
    val = os.environ.get(key, "").strip()
    if not val:
        return None
    return resolve_device(val)


def set_pipewire_defaults(input_spec: str | None, output_spec: str | None):
    """Set PipeWire default source/sink by matching INPUT_DEVICE/OUTPUT_DEVICE name."""
    with pulsectl.Pulse("alexa-routing") as pulse:
        if output_spec and output_spec.lower() not in ("pipewire", "default"):
            needle = output_spec.lower()
            match = next(
                (
                    s
                    for s in pulse.sink_list()
                    if needle in s.description.lower() or needle in s.name.lower()
                ),
                None,
            )
            if match:
                pulse.sink_default_set(match)
            else:
                raise RuntimeError(
                    f"PipeWire sink not found for OUTPUT_DEVICE={output_spec!r}"
                )

        if input_spec and input_spec.lower() not in ("pipewire", "default"):
            needle = input_spec.lower()
            match = next(
                (
                    s
                    for s in pulse.source_list()
                    if "monitor" not in s.name
                    and (needle in s.description.lower() or needle in s.name.lower())
                ),
                None,
            )
            if match:
                pulse.source_default_set(match)
            else:
                raise RuntimeError(
                    f"PipeWire source not found for INPUT_DEVICE={input_spec!r}"
                )


def find_alexa_card(pulse, spec: str | None = None):
    """Return the pulsectl card object matching the spec (name, desc, or index)."""
    if not spec:
        spec = "NewPie"

    spec_lower = spec.lower()
    is_numeric = spec.strip().isdigit()
    spec_index = int(spec) if is_numeric else -1

    for card in pulse.card_list():
        if is_numeric and card.index == spec_index:
            return card
        desc = card.proplist.get("device.description", "").lower()
        name = card.name.lower()
        if spec_lower in desc or spec_lower in name:
            return card
    return None


def detect_connection(card) -> str:
    """Return 'usb', 'bluetooth', or 'internal' based on the card's device.bus property."""
    bus = card.proplist.get("device.bus", "").lower()
    if bus == "usb":
        return "usb"
    if bus == "bluetooth":
        return "bluetooth"
    return "internal"


def enforce_audio_state(
    pulse: pulsectl.Pulse, input_spec: str | None = None, output_spec: str | None = None
) -> tuple[bool, str]:
    """
    Find the configured card, force correct profile if it exists, and set as default sink/source.
    Returns (ok, connection_type).
    """
    # If explicitly using the PipeWire virtual device, consider us connected if PW is alive.
    is_virtual = (output_spec or "").lower() in ("pipewire", "default")

    card = find_alexa_card(pulse, output_spec)
    if not card:
        if is_virtual and pulse.sink_list() and pulse.source_list():
            return True, "virtual"
        return False, "disconnected"

    conn = detect_connection(card)

    # 1. Force Profile if appropriate
    target_profile = None
    if conn == "bluetooth":
        target_profile = "headset-head-unit"
    elif conn == "usb":
        if any(p.name == "pro-audio" for p in card.profile_list):
            target_profile = "pro-audio"

    if target_profile and card.profile_active.name != target_profile:
        if any(p.name == target_profile for p in card.profile_list):
            logger.info(f"Enforcing profile {target_profile} on {card.name}")
            pulse.card_profile_set(card, target_profile)
            time.sleep(0.5)
            card = find_alexa_card(pulse, output_spec)
            if not card:
                return False, "disconnected"

    # 2. Force Routing (Defaults)
    sinks = [s for s in pulse.sink_list() if s.card == card.index]
    sources = [
        s
        for s in pulse.source_list()
        if s.card == card.index and "monitor" not in s.name
    ]

    info = pulse.server_info()

    if sinks:
        sink = next((s for s in sinks if "output" in s.name.lower()), sinks[0])
        if info.default_sink_name != sink.name:
            logger.info(f"Setting default sink: {sink.name}")
            pulse.sink_default_set(sink)

    if sources:
        source = next((s for s in sources if "input" in s.name.lower()), sources[0])
        if info.default_source_name != source.name:
            logger.info(f"Setting default source: {source.name}")
            pulse.source_default_set(source)

    return True, conn


class AudioWatcher(threading.Thread):
    """
    Daemon thread that monitors PipeWire events and enforces audio state.
    """

    def __init__(
        self,
        input_spec: str | None = None,
        output_spec: str | None = None,
        on_status_change: "Callable[[bool, str], None] | None" = None,
    ):
        super().__init__(daemon=True, name="audio-watcher")
        self.input_spec = input_spec
        self.output_spec = output_spec
        self.on_status_change = on_status_change
        self._stop = threading.Event()
        self.connected = False
        self.conn_type = "unknown"

    def stop(self):
        self._stop.set()

    def run(self):
        logger.info(f"Audio watcher started (target: {self.output_spec or 'NewPie'})")
        while not self._stop.is_set():
            try:
                with pulsectl.Pulse("alexa-watcher") as pulse:
                    self._check_and_enforce(pulse)
                    pulse.event_mask_set("card", "sink", "source")
                    pulse.event_callback_set(lambda _: None)

                    last_enforce = 0.0
                    while not self._stop.is_set():
                        pulse.event_listen(timeout=2.0)
                        now = time.monotonic()
                        if now - last_enforce >= 1.0:
                            self._check_and_enforce(pulse)
                            last_enforce = now
            except Exception as e:
                if not self._stop.is_set():
                    logger.error(f"Audio watcher error: {e}")
                    time.sleep(2)

    def _check_and_enforce(self, pulse: pulsectl.Pulse):
        ok, conn = enforce_audio_state(pulse, self.input_spec, self.output_spec)
        if ok != self.connected or conn != self.conn_type:
            if ok and not self.connected:
                logger.info(f"Audio device {conn} connected and configured")

            self.connected = ok
            self.conn_type = conn
            # PortAudio's view of devices can shift on hot-plug — drop the cache.
            invalidate_pipewire_device_cache()
            if self.on_status_change:
                self.on_status_change(ok, conn)


def check_newpie_ready() -> tuple[bool, str]:
    """
    Verify configured audio device is connected and ready.
    """
    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    output_spec = os.environ.get("OUTPUT_DEVICE", "").strip() or None
    is_virtual = (output_spec or "").lower() in ("pipewire", "default")

    with pulsectl.Pulse("alexa-check") as pulse:
        ok, conn = enforce_audio_state(pulse, input_spec, output_spec)
        if not ok:
            print(f"ERROR: Audio device {output_spec or 'NewPie'!r} not found.")
            return False, "unknown"

        if is_virtual:
            return True, "virtual"

        info = pulse.server_info()
        sinks = {s.name: s for s in pulse.sink_list()}
        sources = {s.name: s for s in pulse.source_list()}

        default_sink = sinks.get(info.default_sink_name)
        default_source = sources.get(info.default_source_name)

        target_out = (output_spec or "NewPie").lower()
        if not default_sink or (
            target_out not in default_sink.description.lower()
            and target_out not in default_sink.name.lower()
        ):
            print(
                f"WARNING: Default sink is not the expected device (got: {info.default_sink_name})"
            )
            ok = False

        target_in = (input_spec or "NewPie").lower()
        if not default_source or (
            target_in not in default_source.description.lower()
            and target_in not in default_source.name.lower()
        ):
            print(
                f"WARNING: Default source is not the expected device (got: {info.default_source_name})"
            )
            ok = False

    return ok, conn


def list_devices():
    print("=" * 60)
    print("AUDIO DEVICES")
    print("=" * 60)

    with pulsectl.Pulse("newpie-lister") as pulse:
        info = pulse.server_info()

        cards = pulse.card_list()
        if cards:
            print("\n[Cards]")
            for card in cards:
                desc = card.proplist.get("device.description", card.name)
                conn = detect_connection(card)
                profile = card.profile_active.name if card.profile_active else "off"
                print(f"  {card.index}: {desc} [{conn}]")
                print(f"      Name:    {card.name}")
                print(f"      Profile: {profile}")

        print("\n[Sinks - Output]")
        for sink in pulse.sink_list():
            marker = " [DEFAULT]" if sink.name == info.default_sink_name else ""
            print(f"  {sink.index}: {sink.description}{marker}")
            print(f"      Name: {sink.name}")

        print("\n[Sources - Input]")
        for source in pulse.source_list():
            if "monitor" not in source.name:
                marker = " [DEFAULT]" if source.name == info.default_source_name else ""
                print(f"  {source.index}: {source.description}{marker}")
                print(f"      Name: {source.name}")

    print("\n" + "=" * 60)
    print("Sounddevice / ALSA Devices")
    print("=" * 60)
    import sounddevice as sd
    for i, device in enumerate(sd.query_devices()):
        print(f"  {i}: {device['name']}")
        print(
            f"      In: {device['max_input_channels']} ch, Out: {device['max_output_channels']} ch"
        )


def speakerphone():
    import sounddevice as sd

    print("=" * 60)
    print("NewPie Conference Speakerphone")
    print("=" * 60)

    ok, conn = check_newpie_ready()
    if not ok:
        sys.exit(1)

    input_device = device_from_env("INPUT_DEVICE")
    output_device = device_from_env("OUTPUT_DEVICE")
    if input_device is None or output_device is None:
        pw_device = find_pipewire_device()
        if pw_device is None:
            print(
                "ERROR: PipeWire ALSA device not found and no INPUT_DEVICE/OUTPUT_DEVICE set."
            )
            sys.exit(1)
        if input_device is None:
            input_device = pw_device
        if output_device is None:
            output_device = pw_device

    input_info = sd.query_devices(input_device)
    max_in_channels = input_info["max_input_channels"]

    samplerate = _SAMPLERATE[conn]
    print(f"\nConnection:        {conn}")
    print(
        f"Input device:      {input_device} ({input_info['name']}) [{max_in_channels} ch]"
    )
    print(
        f"Output device:     {output_device} ({sd.query_devices(output_device)['name']})"
    )
    print(f"Sample rate:       {samplerate} Hz")
    print("Starting loopback (mic ch 1..N → mono speaker). Press Ctrl+C to stop.\n")

    frame_count = 0

    def audio_callback(indata, outdata, frames, time, status):
        nonlocal frame_count
        if status:
            print(f"Audio status: {status}", file=sys.stderr)

        # indata has shape (frames, max_in_channels)
        # outdata has shape (frames, 1)
        if max_in_channels > 1:
            outdata[:, 0] = np.mean(indata, axis=1)
        else:
            outdata[:] = indata

        frame_count += frames
        if frame_count % samplerate == 0:
            print(f"  {frame_count // samplerate}s", flush=True)

    try:
        with sd.Stream(
            device=(input_device, output_device),
            samplerate=samplerate,
            blocksize=1024,
            channels=(max_in_channels, 1),
            dtype=np.float32,
            callback=audio_callback,
        ):
            while True:
                sd.sleep(500)
    except KeyboardInterrupt:
        print(f"\nStopped after {frame_count // samplerate}s ({frame_count} frames).")
    except sd.PortAudioError as e:
        print(f"\nAudio error: {e}")
        print("Is the NewPie still connected?")
        sys.exit(1)


def _play_array(audio: np.ndarray, samplerate: int) -> None:
    """Play a float32 numpy audio array via pw-play (PipeWire) or aplay (ALSA fallback)."""
    channels = audio.shape[1] if audio.ndim > 1 else 1
    frames = audio.shape[0]
    duration_s = frames / samplerate
    # Give pw-play 3× the audio duration plus 5 s startup, capped at 30 s.
    play_timeout = min(max(duration_s * 3 + 5, 8), 30)
    data = np.ascontiguousarray(audio).tobytes()

    if _PW_PLAY:
        cmd = [
            _PW_PLAY,
            "-a",
            "--rate",
            str(samplerate),
            "--channels",
            str(channels),
            "--format",
            "f32",
            "-",
        ]
    else:
        cmd = [
            "aplay",
            "-D",
            "pipewire",
            "-r",
            str(samplerate),
            "-f",
            "FLOAT_LE",
            "-c",
            str(channels),
            "-q",
        ]

    with _audio_lock:
        _playback_active.set()
        try:
            subprocess.run(
                cmd,
                input=data,
                timeout=play_timeout,
                check=False,
                stderr=subprocess.DEVNULL,
            )
            if _POST_PLAYBACK_MS > 0:
                time.sleep(_POST_PLAYBACK_MS / 1000.0)
        except Exception as e:
            logger.error(f"_play_array failed: {e}")
        finally:
            _playback_active.clear()


def _play_raw(data: bytes, samplerate: int, channels: int) -> None:
    """Play raw float32 audio via pw-play (native PipeWire) or aplay (ALSA fallback)."""
    # f32 = 4 bytes per sample; compute timeout the same way as _play_array.
    frames = len(data) // (channels * 4)
    duration_s = frames / samplerate
    play_timeout = min(max(duration_s * 3 + 5, 8), 30)

    if _PW_PLAY:
        cmd = [
            _PW_PLAY,
            "-a",  # raw mode: honour --format/--rate/--channels instead of auto-detect
            "--rate",
            str(samplerate),
            "--channels",
            str(channels),
            "--format",
            "f32",
            "-",
        ]
    else:
        cmd = [
            "aplay",
            "-D",
            "pipewire",
            "-r",
            str(samplerate),
            "-f",
            "FLOAT_LE",
            "-c",
            str(channels),
            "-q",
        ]

    with _audio_lock:
        _playback_active.set()
        try:
            subprocess.run(
                cmd,
                input=data,
                timeout=play_timeout,
                check=False,
                stderr=subprocess.DEVNULL,
            )
            if _POST_PLAYBACK_MS > 0:
                time.sleep(_POST_PLAYBACK_MS / 1000.0)
        except Exception as e:
            logger.error(f"Failed to run audio playback command: {e}")
        finally:
            _playback_active.clear()


def play_wav_file(file_path: str) -> None:
    """Play a WAV file via pw-play (native PipeWire) or aplay (ALSA fallback)."""
    if _PW_PLAY:
        cmd = [_PW_PLAY, file_path]
    else:
        cmd = ["aplay", "-D", "pipewire", "-q", file_path]

    with _audio_lock:
        _playback_active.set()
        try:
            subprocess.run(cmd, timeout=60, check=False, stderr=subprocess.DEVNULL)
            if _POST_PLAYBACK_MS > 0:
                time.sleep(_POST_PLAYBACK_MS / 1000.0)
        except Exception:
            pass
        finally:
            _playback_active.clear()


def record_wav_file(file_path: str, duration: float) -> None:
    """Record a WAV file from the default PipeWire source."""
    pw_record = shutil.which("pw-record")
    rate = 16000
    if pw_record:
        count = int(duration * rate)
        cmd = [
            pw_record,
            "--rate",
            str(rate),
            "--channels",
            "1",
            "--format",
            "s16",
            "--sample-count",
            str(count),
            file_path,
        ]
    else:
        cmd = [
            "arecord",
            "-D",
            "pipewire",
            "-d",
            str(int(duration)),
            "-f",
            "S16_LE",
            "-r",
            str(rate),
            file_path,
        ]

    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        logger.error(f"Recording failed: {e}")


def play_tone(name: str):
    """Play a predefined tone by name (startup, success, error, info, warning)."""
    samplerate = 48000
    channels = 2

    def _generate_note(
        freq: float, duration: float, volume: float = 0.60
    ) -> np.ndarray:
        n = int(samplerate * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        # Add a bit of harmonics for a "cooler" sound
        wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
        wave += 0.3 * np.sin(2 * np.pi * freq * 2 * t).astype(np.float32)
        wave += 0.1 * np.sin(2 * np.pi * freq * 3 * t).astype(np.float32)
        wave /= np.max(np.abs(wave))
        # Fade in/out to avoid clicks
        fade_samples = int(samplerate * 0.02)
        envelope = np.ones(n, dtype=np.float32)
        if n > 2 * fade_samples:
            envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
            envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
        mono = wave * envelope * volume
        return np.column_stack([mono, mono])

    def _gap(duration: float) -> np.ndarray:
        return np.zeros((int(samplerate * duration), channels), dtype=np.float32)

    tones = {
        "startup": lambda: np.concatenate(
            [
                _gap(1.0),  # Priming silence to wake up hardware
                _generate_note(523.25, 0.14),  # C5
                _gap(0.03),
                _generate_note(659.25, 0.14),  # E5
                _gap(0.03),
                _generate_note(783.99, 0.14),  # G5
            ]
        ),
        "wake": lambda: np.concatenate(
            [
                _generate_note(440.00, 0.10, volume=0.6),  # A4
                _gap(0.02),
                _generate_note(554.37, 0.15, volume=0.6),  # C#5
            ]
        ),
        "success": lambda: np.concatenate(
            [
                _generate_note(783.99, 0.10),  # G5
                _gap(0.05),
                _generate_note(1046.50, 0.20),  # C6
            ]
        ),
        "error": lambda: np.concatenate(
            [
                _generate_note(261.63, 0.15, volume=0.6),  # C4
                _gap(0.05),
                _generate_note(233.08, 0.30, volume=0.6),  # Bb3 (dissonant)
            ]
        ),
        "info": lambda: _generate_note(880.00, 0.15),  # A5
        "warning": lambda: np.concatenate(
            [
                _generate_note(1318.51, 0.10),  # E6
                _gap(0.05),
                _generate_note(1046.50, 0.10),  # C6
            ]
        ),
    }

    if name not in tones:
        logger.warning(f"Unknown tone name: {name}")
        return

    try:
        audio = tones[name]()
        if _TONE_PREROLL_MS > 0:
            preroll = np.zeros(
                (int(samplerate * _TONE_PREROLL_MS / 1000), channels), dtype=np.float32
            )
            audio = np.concatenate([preroll, audio])
        _play_array(audio, samplerate)
    except Exception as e:
        logger.error(f"play_tone({name}) failed: {e}")


def list_env_devices():
    """Print microphone and speaker tables for use in .env."""
    import sounddevice as sd
    devices = list(sd.query_devices())
    pw_idx = find_pipewire_device()

    col_name = max(len(d["name"]) for d in devices)

    def _table(title, env_key, entries):
        print(title)
        print(f"  {'Idx':>4}  {'Name':<{col_name}}  Channels")
        print(f"  {'─' * 4}  {'─' * col_name}  ────────")
        for i, d in entries:
            note = "  ← PipeWire default" if i == pw_idx else ""
            ch = (
                d["max_input_channels"]
                if "INPUT" in env_key
                else d["max_output_channels"]
            )
            print(f"  {i:>4}  {d['name']:<{col_name}}  {ch}{note}")
        print(f"\n  → set {env_key}=<name or index>")

    mics = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    speakers = [(i, d) for i, d in enumerate(devices) if d["max_output_channels"] > 0]

    _table("Microphones (INPUT_DEVICE):", "INPUT_DEVICE", mics)
    print()
    _table("Speakers (OUTPUT_DEVICE):", "OUTPUT_DEVICE", speakers)


def play_beep(frequency_hz: float, duration_ms: int) -> None:
    """Play a pure-tone beep through the PipeWire default sink via aplay or pw-play."""
    samplerate = 48000
    channels = 2
    n = int(samplerate * duration_ms / 1000)
    fade = min(int(samplerate * 0.01), n // 4)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = np.sin(2 * np.pi * frequency_hz * t).astype(np.float32) * 0.6
    envelope = np.ones(n, dtype=np.float32)
    envelope[:fade] = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)
    mono = wave * envelope
    audio = np.column_stack([mono, mono])
    if _TONE_PREROLL_MS > 0:
        preroll = np.zeros(
            (int(samplerate * _TONE_PREROLL_MS / 1000), channels), dtype=np.float32
        )
        audio = np.concatenate([preroll, audio])
    _play_array(audio, samplerate)


def play_wake_beep(name: str = "wake") -> None:
    if name.lower() == "none":
        return
    play_tone(name)


def play_timeout_beep() -> None:
    play_beep(400, 150)


def play_call_start() -> None:
    """Two rising tones — call connected."""
    play_beep(600, 120)
    play_beep(900, 180)


def play_call_end() -> None:
    """Two falling tones — call ended."""
    play_beep(900, 120)
    play_beep(600, 180)


_UDEV_PATH = "/etc/udev/rules.d/89-alsa-usb-volume.rules"


def _find_alsa_card(needle: str) -> tuple[int, str] | None:
    """Return (card_index, card_id) for the first ALSA card whose id contains needle."""
    import os

    for entry in os.listdir("/proc/asound"):
        if not entry.startswith("card"):
            continue
        try:
            with open(f"/proc/asound/{entry}/id") as f:
                card_id = f.read().strip()
            if needle.lower() in card_id.lower():
                return int(entry[4:]), card_id
        except OSError:
            pass
    return None


def _usb_ids_for_alsa_card(card_index: int) -> tuple[str, str] | None:
    """Return (vendor_id, model_id) by querying udevadm for the ALSA control device."""
    result = subprocess.run(
        ["udevadm", "info", "--name", f"/dev/snd/controlC{card_index}"],
        capture_output=True,
        text=True,
    )
    vendor = model = None
    for line in result.stdout.splitlines():
        if "ID_VENDOR_ID=" in line:
            vendor = line.split("=", 1)[1]
        elif "ID_MODEL_ID=" in line:
            model = line.split("=", 1)[1]
    if vendor and model:
        return vendor, model
    return None


def setup_audio() -> None:
    """Set output device PCM hardware volume to 100% and persist it across reboots."""
    output_spec = os.environ.get("OUTPUT_DEVICE", "").strip()
    if not output_spec:
        print("ERROR: OUTPUT_DEVICE is not set — add it to config.yaml under env:")
        sys.exit(1)

    card = _find_alsa_card(output_spec)
    if card is None:
        print(f"ERROR: No ALSA card matching OUTPUT_DEVICE={output_spec!r}")
        print("  Is the device connected?")
        sys.exit(1)

    card_index, card_id = card
    print(
        f"Found {card_id!r} at ALSA card {card_index} (OUTPUT_DEVICE={output_spec!r})"
    )

    # Set PCM Playback Volume to 100%
    result = subprocess.run(
        ["amixer", "-c", str(card_index), "set", "PCM", "100%"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: amixer failed: {result.stderr.strip()}")
        sys.exit(1)
    print("PCM Playback Volume set to 100%")

    # Save ALSA state
    result = subprocess.run(
        ["sudo", "alsactl", "store"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: alsactl store failed: {result.stderr.strip()}")
        sys.exit(1)
    print("ALSA state saved")

    # Build and install udev rule based on the device's actual USB IDs
    ids = _usb_ids_for_alsa_card(card_index)
    if ids is None:
        print(
            "WARNING: Could not read USB IDs — skipping udev rule (device may not be USB)"
        )
        return

    vendor_id, model_id = ids
    udev_rule = (
        f"# Restore ALSA mixer state for {card_id} on connect\n"
        f'ACTION=="add", SUBSYSTEM=="sound", \\\n'
        f'  ENV{{ID_VENDOR_ID}}=="{vendor_id}", ENV{{ID_MODEL_ID}}=="{model_id}", \\\n'
        f'  RUN+="/usr/sbin/alsactl restore"\n'
    )

    result = subprocess.run(
        ["sudo", "tee", _UDEV_PATH],
        input=udev_rule,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: writing udev rule failed: {result.stderr.strip()}")
        sys.exit(1)

    subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], check=True)
    print(f"udev rule installed at {_UDEV_PATH}")

    # Boost microphone input gain via PipeWire (persisted by WirePlumber state).
    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or output_spec
    with pulsectl.Pulse("alexa-setup") as pulse:
        needle = input_spec.lower()
        source = next(
            (
                s
                for s in pulse.source_list()
                if "monitor" not in s.name
                and (needle in s.description.lower() or needle in s.name.lower())
            ),
            None,
        )
    if source is None:
        print(
            f"WARNING: No PipeWire source found for {input_spec!r} — skipping mic gain"
        )
    else:
        result = subprocess.run(
            ["pactl", "set-source-volume", source.name, "300%"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"Microphone gain set to 3x on {source.name}")
        else:
            print(f"WARNING: pactl set-source-volume failed: {result.stderr.strip()}")

    print(f"Done. {card_id!r} volumes will be restored automatically on every connect.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--list", "-l", "list"):
        list_devices()
    else:
        speakerphone()


def main_devices():
    list_env_devices()


def main_test():
    import tempfile
    import os
    from alexa_custom.tts import init_engine, get_engine
    from alexa_custom.config import load_config

    print("--- Audio System Test ---")

    # Load config to respect INPUT_DEVICE / OUTPUT_DEVICE and env: section
    config = load_config("config.yaml")

    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    output_spec = os.environ.get("OUTPUT_DEVICE", "").strip() or None

    try:
        set_pipewire_defaults(input_spec, output_spec)
    except Exception as e:
        print(f"WARNING: Could not set PipeWire defaults: {e}")

    print("1. Playing tone...")
    play_tone("info")

    print("2. TTS: Asking for name...")
    # Initialize engine with settings from config if available
    if config:
        init_engine(
            backend_type=config.tts_backend,
            voice=config.tts_voice,
            preroll_ms=config.tts_preroll_ms,
        )
    else:
        init_engine(backend_type="piper")
    
    get_engine().say("Ciao, come ti chiami?")

    print("3. Recording 5 seconds of audio...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = f.name
    
    try:
        print("   [RECORDING NOW - SPEAK INTO MICROPHONE]")
        record_wav_file(tmp_wav, 5.0)
        print("   [DONE]")

        print("4. TTS: Announcing playback...")
        get_engine().say("Ecco la registrazione:")

        print("5. Playing back recorded sound...")
        play_wav_file(tmp_wav)
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)

    print("\nTest completed.")


if __name__ == "__main__":
    main()
