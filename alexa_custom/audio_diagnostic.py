"""CLI / diagnostic tools for audio hardware.

These functions are only used by interactive entry-points (alexa-devices,
alexa-audio, alexa-audio-doctor, alexa-setup) and setup scripts.
Runtime audio state and routing live in audio_hw.py.

Dependency direction: diagnostics → runtime (audio_hw), never the reverse.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from alexa_custom.audio_hw import (
    _find_alsa_card,
    _find_pipewire_source,
    check_newpie_ready,
    detect_connection,
    device_from_env,
    find_pipewire_device,
    get_sample_rates,
    pulse_session,
)

_UDEV_PATH = "/etc/udev/rules.d/89-alsa-usb-volume.rules"


def list_devices():
    print("=" * 60)
    print("AUDIO DEVICES")
    print("=" * 60)

    with pulse_session("newpie-lister") as pulse:
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

    samplerate = get_sample_rates().get(conn, 48000)
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

    def audio_callback(indata, outdata, frames, _time, status):
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


def _amixer_pcm_percent(card_index: int) -> int | None:
    """Return the NewPie hardware PCM level as a percentage, or None if unreadable."""
    try:
        result = subprocess.run(
            ["amixer", "-c", str(card_index), "sget", "PCM"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    m = re.search(r"\[(\d+)%\]", result.stdout)
    return int(m.group(1)) if m else None


def audio_doctor() -> int:
    """Check each audio invariant from the platform notes and print pass/fail.

    Returns the number of failed checks (0 == healthy) so callers/CI can use the
    exit code. Warnings (degraded but not broken) do not count as failures.
    """
    results: list[tuple[str, bool, str]] = []
    warnings: list[tuple[str, str]] = []

    def ok(name: str, passed: bool, detail: str = "") -> None:
        results.append((name, passed, detail))

    def warn(name: str, detail: str) -> None:
        warnings.append((name, detail))

    # 1. Required binaries
    for tool in ("amixer", "pactl", "pw-play", "parec", "wpctl"):
        present = shutil.which(tool) is not None
        if tool in ("pw-play", "parec", "amixer", "pactl"):
            ok(f"binary:{tool}", present, "" if present else "not found in PATH")
        elif not present:
            warn(f"binary:{tool}", "not found (optional)")

    # 2. NewPie present as an ALSA card
    card = _find_alsa_card("NewPie")
    ok("newpie:alsa-card", card is not None, "NewPie not found in /proc/asound")

    # 3. Hardware PCM not muted
    if card is not None:
        pct = _amixer_pcm_percent(card[0])
        if pct is None:
            warn("newpie:pcm-level", "could not read PCM level")
        else:
            ok(
                "newpie:pcm-level",
                pct >= 100,
                f"PCM at {pct}% (expected 100% — run `task audio:restart`)",
            )

    # 4. Default routing points at NewPie
    try:
        routed, conn = check_newpie_ready()
        ok("newpie:default-routing", routed, f"connection={conn}")
    except Exception as e:
        warn("newpie:default-routing", f"check failed: {e}")

    # 5. No stale switch-on-connect drop-ins (crash this board's PipeWire 1.4.2)
    home = Path.home()
    stale = [
        home / ".config/pipewire/pipewire.conf.d/99-switch-on-connect.conf",
        home / ".config/pipewire/pipewire-pulse.conf.d/99-switch-on-connect.conf",
    ]
    present_stale = [str(p) for p in stale if p.exists()]
    ok(
        "pipewire:no-switch-on-connect",
        not present_stale,
        f"remove: {', '.join(present_stale)}" if present_stale else "",
    )

    # 6. USB autosuspend disabled for the NewPie
    autosuspend_rule = Path("/etc/udev/rules.d/99-newpie-no-autosuspend.rules")
    ok(
        "newpie:no-autosuspend",
        autosuspend_rule.exists(),
        "udev rule missing — run `task audio:setup`",
    )

    # 7. PCM-restore user service installed
    unmute_service = home / ".config/systemd/user/alsa-pcm-unmute.service"
    ok(
        "service:alsa-pcm-unmute",
        unmute_service.exists(),
        "not installed — run `task audio:setup`",
    )
    if unmute_service.exists():
        try:
            enabled = subprocess.run(
                ["systemctl", "--user", "is-enabled", "alsa-pcm-unmute.service"],
                capture_output=True,
                text=True,
                check=False,
            )
            if enabled.stdout.strip() != "enabled":
                warn("service:alsa-pcm-unmute", "installed but not enabled")
        except FileNotFoundError:
            warn("service:alsa-pcm-unmute", "systemctl not available")

    # Report
    print("=" * 60)
    print(" AUDIO DOCTOR")
    print("=" * 60)
    failures = 0
    for name, passed, detail in results:
        mark = "\x1b[32mPASS\x1b[0m" if passed else "\x1b[31mFAIL\x1b[0m"
        suffix = f"  — {detail}" if detail and not passed else ""
        print(f"  [{mark}] {name}{suffix}")
        if not passed:
            failures += 1
    for name, detail in warnings:
        print(f"  [\x1b[33mWARN\x1b[0m] {name}  — {detail}")
    print("=" * 60)
    if failures:
        print(f"{failures} check(s) failed. See suggestions above.")
    else:
        print("All critical checks passed.")
    return failures
