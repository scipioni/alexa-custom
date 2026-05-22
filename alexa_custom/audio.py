#!/usr/bin/env python3
import os
import subprocess
import sys
import sounddevice as sd
import numpy as np
import pulsectl

# Sample rates by connection type
_SAMPLERATE = {"usb": 48000, "bluetooth": 16000}


def find_pipewire_device():
    """Return the sounddevice index for the PipeWire ALSA device."""
    return next(
        (i for i, d in enumerate(sd.query_devices()) if d["name"] == "pipewire"),
        None,
    )


def resolve_device(name_or_index: str) -> int:
    """Resolve a device name substring or numeric index string to a sounddevice index."""
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
        if output_spec:
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

        if input_spec:
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


def find_newpie_card(pulse):
    """Return the pulsectl card object for the NewPie, or None."""
    for card in pulse.card_list():
        if "NewPie" in card.proplist.get("device.description", ""):
            return card
    return None


def detect_connection(card) -> str:
    """Return 'usb' or 'bluetooth' based on the card's device.bus property."""
    return "usb" if card.proplist.get("device.bus", "") == "usb" else "bluetooth"


def check_newpie_ready() -> tuple[bool, str]:
    """
    Verify NewPie is connected and ready for full-duplex audio.
    Returns (ok, connection_type) where connection_type is 'usb' or 'bluetooth'.
    Prints warnings for anything wrong.
    """
    ok = True
    with pulsectl.Pulse("newpie-check") as pulse:
        card = find_newpie_card(pulse)
        if card is None:
            print("ERROR: NewPie not found. Is it connected (USB or Bluetooth)?")
            print("  USB:       plug in the USB cable")
            print("  Bluetooth: bluetoothctl connect <MAC>")
            return False, "unknown"

        conn = detect_connection(card)

        if conn == "bluetooth":
            profile = card.profile_active.name if card.profile_active else "off"
            if profile != "headset-head-unit":
                print(
                    f"WARNING: NewPie Bluetooth profile is '{profile}', expected 'headset-head-unit'"
                )
                print(f"  Fix: pactl set-card-profile {card.name} headset-head-unit")
                ok = False

        info = pulse.server_info()
        sinks = {s.name: s for s in pulse.sink_list()}
        sources = {s.name: s for s in pulse.source_list()}

        default_sink = sinks.get(info.default_sink_name)
        default_source = sources.get(info.default_source_name)

        if default_sink is None or "NewPie" not in default_sink.description:
            print(
                f"WARNING: Default sink is not NewPie (got: {info.default_sink_name})"
            )
            print("  Fix: wpctl set-default <newpie-sink-id>")
            ok = False

        if default_source is None or "NewPie" not in default_source.description:
            print(
                f"WARNING: Default source is not NewPie (got: {info.default_source_name})"
            )
            print("  Fix: wpctl set-default <newpie-source-id>")
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
    for i, device in enumerate(sd.query_devices()):
        print(f"  {i}: {device['name']}")
        print(
            f"      In: {device['max_input_channels']} ch, Out: {device['max_output_channels']} ch"
        )


def speakerphone():
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

    samplerate = _SAMPLERATE[conn]
    print(f"\nConnection:        {conn}")
    print(
        f"Input device:      {input_device} ({sd.query_devices(input_device)['name']})"
    )
    print(
        f"Output device:     {output_device} ({sd.query_devices(output_device)['name']})"
    )
    print(f"Sample rate:       {samplerate} Hz")
    print("Starting loopback (mic → speaker). Press Ctrl+C to stop.\n")

    frame_count = 0

    def audio_callback(indata, outdata, frames, time, status):
        nonlocal frame_count
        if status:
            print(f"Audio status: {status}", file=sys.stderr)
        outdata[:] = indata
        frame_count += frames
        if frame_count % samplerate == 0:
            print(f"  {frame_count // samplerate}s", flush=True)

    try:
        with sd.Stream(
            device=(input_device, output_device),
            samplerate=samplerate,
            blocksize=1024,
            channels=1,
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


def play_startup_chime():
    """Play a short ascending chime (C5-E5-G5) through the PipeWire default sink.

    Uses aplay instead of PortAudio because PortAudio's ALSA backend hangs on
    the pipewire virtual device after a routing change.
    """
    samplerate = 48000
    channels = 2
    note_duration = 0.14
    gap_duration = 0.03
    fade_samples = int(samplerate * 0.04)

    def _note(freq: float) -> np.ndarray:
        n = int(samplerate * note_duration)
        t = np.linspace(0, note_duration, n, endpoint=False)
        wave = np.sin(2 * np.pi * freq * t).astype(np.float32)
        wave += 0.3 * np.sin(2 * np.pi * freq * 2 * t).astype(np.float32)
        wave /= np.max(np.abs(wave))
        envelope = np.ones(n, dtype=np.float32)
        envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
        envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
        mono = wave * envelope * 0.45
        return np.column_stack([mono, mono])

    gap = np.zeros((int(samplerate * gap_duration), channels), dtype=np.float32)
    chime = np.concatenate(
        [
            _note(523.25),  # C5
            gap,
            _note(659.25),  # E5
            gap,
            _note(783.99),  # G5
        ]
    )
    subprocess.run(
        [
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
        ],
        input=chime.tobytes(),
        timeout=5,
        check=True,
    )


def list_env_devices():
    """Print microphone and speaker tables for use in .env."""
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
    """Play a pure-tone beep through the PipeWire default sink via aplay."""
    samplerate = 48000
    channels = 2
    n = int(samplerate * duration_ms / 1000)
    fade = min(int(samplerate * 0.01), n // 4)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = np.sin(2 * np.pi * frequency_hz * t).astype(np.float32) * 0.4
    envelope = np.ones(n, dtype=np.float32)
    envelope[:fade] = np.linspace(0, 1, fade)
    envelope[-fade:] = np.linspace(1, 0, fade)
    mono = wave * envelope
    audio = np.column_stack([mono, mono])
    subprocess.run(
        [
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
        ],
        input=audio.tobytes(),
        timeout=3,
        check=False,
    )


def play_wake_beep() -> None:
    play_beep(800, 150)


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
        capture_output=True, text=True,
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
    from alexa_custom._env import load_env
    load_env()

    output_spec = os.environ.get("OUTPUT_DEVICE", "").strip()
    if not output_spec:
        print("ERROR: OUTPUT_DEVICE is not set in .env")
        sys.exit(1)

    card = _find_alsa_card(output_spec)
    if card is None:
        print(f"ERROR: No ALSA card matching OUTPUT_DEVICE={output_spec!r}")
        print("  Is the device connected?")
        sys.exit(1)

    card_index, card_id = card
    print(f"Found {card_id!r} at ALSA card {card_index} (OUTPUT_DEVICE={output_spec!r})")

    # Set PCM Playback Volume to 100%
    result = subprocess.run(
        ["amixer", "-c", str(card_index), "set", "PCM", "100%"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: amixer failed: {result.stderr.strip()}")
        sys.exit(1)
    print("PCM Playback Volume set to 100%")

    # Save ALSA state
    result = subprocess.run(["sudo", "alsactl", "store"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: alsactl store failed: {result.stderr.strip()}")
        sys.exit(1)
    print("ALSA state saved")

    # Build and install udev rule based on the device's actual USB IDs
    ids = _usb_ids_for_alsa_card(card_index)
    if ids is None:
        print("WARNING: Could not read USB IDs — skipping udev rule (device may not be USB)")
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
        input=udev_rule, capture_output=True, text=True,
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
                s for s in pulse.source_list()
                if "monitor" not in s.name
                and (needle in s.description.lower() or needle in s.name.lower())
            ),
            None,
        )
    if source is None:
        print(f"WARNING: No PipeWire source found for {input_spec!r} — skipping mic gain")
    else:
        result = subprocess.run(
            ["pactl", "set-source-volume", source.name, "300%"],
            capture_output=True, text=True,
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


if __name__ == "__main__":
    main()
