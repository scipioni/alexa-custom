from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pulsectl
import yaml

logger = logging.getLogger(__name__)

_input_gain_lock = threading.Lock()

# State variables managed through configuration
_POST_PLAYBACK_MS = int(os.environ.get("AUDIO_POST_PLAYBACK_MS", "100"))
_TONE_PREROLL_MS = int(os.environ.get("AUDIO_TONE_PREROLL_MS", "300"))
_SAMPLERATE = {"usb": 48000, "bluetooth": 16000}
_DEFAULT_CARD_NAME = "NewPie"
_OUTPUT_VOLUME = 0.5
_INPUT_GAIN = 1.0

_pw_device_resolved = False
_pw_device_index: int | None = None
_UDEV_PATH = "/etc/udev/rules.d/89-alsa-usb-volume.rules"
_STATE_FILE = "conf/state.yaml"


def save_volume_config(volume: float) -> None:
    """Save volume to config.yaml for persistence."""
    config_file = Path("conf/config.yaml")
    if not config_file.exists():
        logger.warning("config.yaml not found, cannot persist volume state")
        return

    try:
        import yaml
        with open(config_file, "r") as f:
            config = yaml.safe_load(f) or {}

        if not isinstance(config, dict):
            logger.warning("config.yaml has invalid structure, cannot persist volume state")
            return

        config.setdefault("audio", {})
        config["audio"]["output_volume"] = volume

        with open(config_file, "w") as f:
            yaml.safe_dump(config, f)
        logger.info(f"Updated config.yaml with volume: {volume:.0%}")

    except Exception as e:
        logger.warning("Failed to save volume to config.yaml: %s", e)


def configure(cfg) -> None:
    """Update module-level audio parameters from ActionsConfig."""
    global \
        _POST_PLAYBACK_MS, \
        _TONE_PREROLL_MS, \
        _SAMPLERATE, \
        _DEFAULT_CARD_NAME, \
        _OUTPUT_VOLUME, \
        _INPUT_GAIN
    _POST_PLAYBACK_MS = int(cfg.audio.post_playback_ms)
    _TONE_PREROLL_MS = int(cfg.audio.tone_preroll_ms)
    _SAMPLERATE = dict(cfg.audio.sample_rates)
    _DEFAULT_CARD_NAME = cfg.audio.card_name
    _OUTPUT_VOLUME = cfg.audio.output_volume
    _INPUT_GAIN = cfg.audio.input_gain


def get_output_volume() -> float:
    return _OUTPUT_VOLUME


def get_input_gain() -> float:
    return _INPUT_GAIN


def get_post_playback_ms() -> int:
    return _POST_PLAYBACK_MS


def get_tone_preroll_ms() -> int:
    return _TONE_PREROLL_MS


def get_sample_rates() -> dict[str, int]:
    return _SAMPLERATE


def get_default_card_name() -> str:
    return _DEFAULT_CARD_NAME


def _restore_hw_pcm(card: int | None = None) -> None:
    """Restore ALSA hardware PCM to 100% after any pulsectl interaction.

    Resolves the NewPie card dynamically unless `card` is explicitly passed
    (for test overrides).  When no NewPie is connected the call is a no-op.
    """
    if card is None:
        result = _find_alsa_card("NewPie")
        if result is None:
            logger.debug("_restore_hw_pcm: no NewPie found, skipping")
            return
        card_index, _ = result
    else:
        card_index = card
    subprocess.run(
        ["amixer", "-c", str(card_index), "sset", "PCM", "100%"],
        capture_output=True,
        check=False,
    )


def find_pipewire_device():
    """Return the sounddevice index for the PipeWire ALSA device."""
    import sounddevice as sd

    return next(
        (i for i, d in enumerate(sd.query_devices()) if d["name"] == "pipewire"),
        None,
    )


def get_pipewire_device() -> int | None:
    """Cached lookup of the PortAudio index of the PipeWire ALSA device."""
    global _pw_device_resolved, _pw_device_index
    if not _pw_device_resolved:
        _pw_device_index = find_pipewire_device()
        _pw_device_resolved = True
    return _pw_device_index


def invalidate_pipewire_device_cache() -> None:
    """Clear the cached PortAudio device index."""
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
    _restore_hw_pcm()


def find_alexa_card(pulse, spec: str | None = None):
    """Return the pulsectl card object matching the spec (name, desc, or index)."""
    if not spec:
        spec = _DEFAULT_CARD_NAME

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


def set_output_volume(
    pulse: pulsectl.Pulse, output_spec: str | None, volume: float
) -> None:
    """Set the in-app output volume scalar.

    The system mixer is intentionally not touched — volume attenuation is applied
    digitally to all audio generated by this daemon (TTS, tones, WAV playback)
    via ``get_output_volume()``.  The global is also read by ``pw-play`` for
    WAV files and by the TTS engine.
    """
    global _OUTPUT_VOLUME
    _OUTPUT_VOLUME = volume
    if volume <= 0:
        return
    logger.info(f"Output volume set to {volume:.0%} (digital scaling)")
    _restore_hw_pcm()


def set_input_gain(
    pulse: pulsectl.Pulse | None, input_spec: str | None, gain: float
) -> None:
    """Set the NewPie microphone gain.

    Tries to set the hardware source volume via ``pactl set-source-volume``
    first.  If the NewPie PipeWire source cannot be located, falls back to
    updating the software-scaling global used by the STT capture pipeline.
    """
    global _INPUT_GAIN

    with _input_gain_lock:
        hw_ok = False
        source_name = _find_pipewire_source(input_spec)
        if source_name is not None:
            _restore_hw_pcm()
            pct = int(max(0.0, gain) * 100)
            result = subprocess.run(
                ["pactl", "set-source-volume", source_name, f"{pct}%"],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                logger.info(f"Mic gain set to {pct}% on {source_name} (OS level)")
                hw_ok = True
            else:
                logger.warning(
                    f"pactl set-source-volume failed: "
                    f"{result.stderr.decode(errors='replace').strip()} — "
                    f"falling back to software scaling"
                )
        else:
            label = f"'{input_spec}'" if input_spec else "default source"
            logger.warning(
                f"PipeWire source {label} not found; "
                f"falling back to software scaling for input gain"
            )

        _INPUT_GAIN = 1.0 if hw_ok else max(0.0, gain)
        if not hw_ok:
            logger.warning(f"Input gain {gain:.0%} applied in software (CPU overhead, clipping risk)")


def enforce_audio_state(
    pulse: pulsectl.Pulse, input_spec: str | None = None, output_spec: str | None = None
) -> tuple[bool, str]:
    """Find configured card, force profile if it exists, and set default sink/source."""
    is_virtual = (output_spec or "").lower() in ("pipewire", "default")

    card = find_alexa_card(pulse, output_spec)
    if not card:
        if is_virtual and pulse.sink_list() and pulse.source_list():
            return True, "virtual"
        return False, "disconnected"

    conn = detect_connection(card)

    target_profile = None
    if conn == "bluetooth":
        target_profile = "headset-head-unit"

    if target_profile and card.profile_active.name != target_profile:
        if any(p.name == target_profile for p in card.profile_list):
            logger.info(f"Enforcing profile {target_profile} on {card.name}")
            pulse.card_profile_set(card, target_profile)
            time.sleep(0.5)
            card = find_alexa_card(pulse, output_spec)
            if not card:
                return False, "disconnected"

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


def check_newpie_ready(
    input_spec: str | None = None,
    output_spec: str | None = None,
) -> tuple[bool, str]:
    """Verify configured audio device is connected and ready."""
    if input_spec is None:
        input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    if output_spec is None:
        output_spec = os.environ.get("OUTPUT_DEVICE", "").strip() or None
    is_virtual = (output_spec or "").lower() in ("pipewire", "default")

    with pulsectl.Pulse("alexa-check") as pulse:
        ok, conn = enforce_audio_state(pulse, input_spec, output_spec)
        if not ok:
            print(
                f"ERROR: Audio device {output_spec or _DEFAULT_CARD_NAME!r} not found."
            )
            return False, "unknown"

        if is_virtual:
            return True, "virtual"

        info = pulse.server_info()
        sinks = {s.name: s for s in pulse.sink_list()}
        sources = {s.name: s for s in pulse.source_list()}

        default_sink = sinks.get(info.default_sink_name)
        default_source = sources.get(info.default_source_name)

        target_out = (output_spec or _DEFAULT_CARD_NAME).lower()
        if not default_sink or (
            target_out not in default_sink.description.lower()
            and target_out not in default_sink.name.lower()
        ):
            print(
                f"WARNING: Default sink is not the expected device (got: {info.default_sink_name})"
            )
            ok = False

        target_in = (input_spec or _DEFAULT_CARD_NAME).lower()
        if not default_source or (
            target_in not in default_source.description.lower()
            and target_in not in default_source.name.lower()
        ):
            print(
                f"WARNING: Default source is not the expected device (got: {info.default_source_name})"
            )
            ok = False

    _restore_hw_pcm()
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


def _find_alsa_card(needle: str) -> tuple[int, str] | None:
    """Return (card_index, card_id) for first ALSA card whose id contains needle."""
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


def _find_pipewire_source(input_spec: str | None) -> str | None:
    """Return the PipeWire source name matching input_spec, or None if not found.

    Matches against both source description and source name.
    Excludes monitor sources (they represent playback outputs, not mic inputs).
    When input_spec is None, returns the server default source.
    """
    with pulsectl.Pulse("alexa-source-lookup") as pulse:
        if input_spec is None:
            info = pulse.server_info()
            return info.default_source_name or None
        needle = input_spec.lower()
        for s in pulse.source_list():
            if "monitor" in s.name:
                continue
            if needle in s.description.lower() or needle in s.name.lower():
                return s.name
    return None


def _usb_ids_for_alsa_card(card_index: int) -> tuple[str, str] | None:
    """Return (vendor_id, model_id) by querying udevadm."""
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
    cfg = None
    output_spec = os.environ.get("OUTPUT_DEVICE", "").strip()
    if not output_spec:
        if os.path.exists("conf/config.yaml"):
            from alexa_custom.config import load_config, load_secrets

            load_secrets("conf/secrets.yaml")
            cfg = load_config("conf/config.yaml")
            if cfg and cfg.audio.output_device:
                output_spec = cfg.audio.output_device
    if not output_spec:
        print(
            "ERROR: OUTPUT_DEVICE is not set — set it in config.yaml under env: or export OUTPUT_DEVICE"
        )
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

    result = subprocess.run(
        ["amixer", "-c", str(card_index), "set", "PCM", "100%"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: amixer failed: {result.stderr.strip()}")
        sys.exit(1)
    print("PCM Playback Volume set to 100%")

    result = subprocess.run(
        ["sudo", "alsactl", "store"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"ERROR: alsactl store failed: {result.stderr.strip()}")
        sys.exit(1)
    print("ALSA state saved")

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

    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or output_spec
    input_gain_pct = int((cfg.audio.input_gain if cfg else 1.0) * 100)
    source_name = _find_pipewire_source(input_spec)
    if source_name is None:
        print(
            f"WARNING: No PipeWire source found for {input_spec!r} — skipping mic gain"
        )
    else:
        result = subprocess.run(
            ["pactl", "set-source-volume", source_name, f"{input_gain_pct}%"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"Microphone gain set to {input_gain_pct}% on {source_name}")
        else:
            print(f"WARNING: pactl set-source-volume failed: {result.stderr.strip()}")

    print(f"Done. {card_id!r} volumes will be restored automatically on every connect.")
