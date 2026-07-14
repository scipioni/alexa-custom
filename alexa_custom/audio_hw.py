from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pulsectl

logger = logging.getLogger(__name__)

_input_gain_lock = threading.Lock()

# PipeWire names every USB audio object with these prefixes, regardless of
# vendor — the basis for device-agnostic ("auto") matching.
USB_SINK_PREFIX = "alsa_output.usb-"
USB_SOURCE_PREFIX = "alsa_input.usb-"


def is_auto_spec(spec: str | None) -> bool:
    """True when the device spec asks for automatic USB-audio detection."""
    return spec is not None and spec.strip().lower() == "auto"


# Mutable audio parameters, updated by configure()/setters at runtime.
# Centralised in one object so there is a single source of truth: always read
# these through the get_*() accessors, never via a `from audio_hw import _X`
# snapshot (which captures the value at import time and silently ignores
# hot-reload). The accessors guarantee every consumer sees the current value.
@dataclass
class _AudioState:
    post_playback_ms: int = int(os.environ.get("AUDIO_POST_PLAYBACK_MS", "100"))
    tone_preroll_ms: int = int(os.environ.get("AUDIO_TONE_PREROLL_MS", "300"))
    samplerate: dict[str, int] = field(
        default_factory=lambda: {"usb": 48000, "bluetooth": 16000}
    )
    default_card_name: str | None = None
    output_volume: float = 0.5
    output_sink: str | None = None
    output_spec: str | None = None
    output_sink_dirty: bool = False
    input_gain: float = 1.0
    hw_gain_applied: bool = False


_state = _AudioState()

_STATE_FILE = "conf/state.yaml"

# Fired by set_active_gst_profile(); the STT worker clears it and restarts
# the capture process so the new profile takes effect without a full restart.
gst_profile_change_event = threading.Event()

# Optional callbacks invoked (with the new profile name) when the active
# GStreamer capture profile changes.  Register via register_profile_callback().
_profile_callbacks: list = []


# STT-level overrides carried by the active profile (rms_threshold, vad_silence_ms).
# Stored in memory only — derived from config at the time the profile is activated.
_profile_stt_overrides: dict = {}


def set_profile_stt_overrides(overrides: dict) -> None:
    global _profile_stt_overrides
    _profile_stt_overrides = dict(overrides)


def get_profile_stt_overrides() -> dict:
    return dict(_profile_stt_overrides)


def register_profile_callback(cb) -> None:
    """Register a callable(profile: str) notified when the active GST profile changes."""
    _profile_callbacks.append(cb)


def unregister_profile_callback(cb) -> None:
    try:
        _profile_callbacks.remove(cb)
    except ValueError:
        pass


def _load_state_file() -> dict:
    """Read conf/state.yaml, return empty dict on any error."""
    import yaml

    state_file = Path(_STATE_FILE)
    if not state_file.exists():
        return {}
    try:
        with open(state_file) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Failed to read %s: %s", _STATE_FILE, e)
        return {}


def _save_state_file(state: dict) -> None:
    """Write dict to conf/state.yaml."""
    import yaml

    state_file = Path(_STATE_FILE)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(state_file, "w") as f:
            yaml.safe_dump(state, f)
    except Exception as e:
        logger.warning("Failed to write %s: %s", _STATE_FILE, e)


def save_volume_config(volume: float) -> None:
    """Save output volume to state.yaml for persistence across restarts."""
    state = _load_state_file()
    state["output_volume"] = volume
    _save_state_file(state)
    logger.info(f"Saved volume to {_STATE_FILE}: {volume:.0%}")


def load_volume_state() -> float | None:
    """Load persisted output volume from state.yaml, returns None if absent."""
    volume = _load_state_file().get("output_volume")
    if volume is not None and 0.0 <= volume <= 1.0:
        return float(volume)
    return None


def save_input_gain_config(gain: float) -> None:
    """Save calibrated input gain to state.yaml for persistence across restarts."""
    state = _load_state_file()
    state["input_gain"] = gain
    _save_state_file(state)
    logger.info(f"Saved input gain to {_STATE_FILE}: {gain:.2f}")


def load_input_gain_state() -> float | None:
    """Load persisted input gain from state.yaml, returns None if absent."""
    gain = _load_state_file().get("input_gain")
    if gain is not None and gain >= 0.0:
        return float(gain)
    return None


def save_gstreamer_overrides(overrides: dict) -> None:
    """Save GStreamer overrides to state.yaml for persistence across restarts."""
    state = _load_state_file()
    state["gstreamer_override"] = overrides
    _save_state_file(state)
    logger.info(f"Saved GStreamer overrides to {_STATE_FILE}: {overrides}")


def load_gstreamer_overrides() -> dict | None:
    """Load persisted GStreamer overrides from state.yaml, returns None if absent."""
    overrides = _load_state_file().get("gstreamer_override")
    if isinstance(overrides, dict):
        return overrides
    return None


def get_active_gst_profile() -> str:
    """Return the persisted GStreamer capture profile name (default: 'normal')."""
    return str(_load_state_file().get("gst_profile", "normal"))


def signal_capture_restart() -> None:
    """Ask the STT worker to restart its capture subprocess on the next chunk.

    Generalizes the profile-change signal (`gst_profile_change_event`) to any
    event that should make a long-running capture re-read config or
    re-resolve its device: a config hot-reload or an audio device
    reconnect. The recognition loop already re-reads config and re-resolves
    the capture source at the top of every restart, so reusing this one
    signal is sufficient — no separate "config changed" event is needed.
    """
    gst_profile_change_event.set()


def set_active_gst_profile(profile: str) -> None:
    """Persist a new GStreamer capture profile and signal the STT worker to restart."""
    state = _load_state_file()
    state["gst_profile"] = profile
    _save_state_file(state)
    gst_profile_change_event.set()
    logger.info("GStreamer audio profile changed to: %s", profile)
    for cb in list(_profile_callbacks):
        try:
            cb(profile)
        except Exception as exc:
            logger.warning("Profile callback error: %s", exc)


def configure(cfg) -> None:
    """Update audio parameters from ActionsConfig."""
    _state.post_playback_ms = int(cfg.audio.post_playback_ms)
    _state.tone_preroll_ms = int(cfg.audio.tone_preroll_ms)
    _state.samplerate = dict(cfg.audio.sample_rates)
    _state.default_card_name = cfg.audio.card_name
    _state.output_volume = cfg.audio.output_volume
    _state.input_gain = cfg.audio.input_gain

    state_vol = load_volume_state()
    if state_vol is not None:
        _state.output_volume = state_vol

    state_gain = load_input_gain_state()
    if state_gain is not None:
        _state.input_gain = state_gain

    overrides = load_gstreamer_overrides()
    if overrides and hasattr(cfg.audio, "gstreamer"):
        for k, v in overrides.items():
            if hasattr(cfg.audio.gstreamer, k):
                setattr(cfg.audio.gstreamer, k, v)

    _state.output_spec = cfg.audio.output_device
    resolve_output_sink(cfg.audio.output_device)


def get_output_volume() -> float:
    return _state.output_volume


def get_output_sink() -> str | None:
    """Return the cached PipeWire sink name, re-resolving first if a device
    (re)connect invalidated it (see invalidate_output_sink()) — so playback
    never targets a node name that belonged to a replugged/swapped device."""
    if _state.output_sink_dirty:
        resolve_output_sink(_state.output_spec, retries=1)
        _state.output_sink_dirty = False
    return _state.output_sink


def invalidate_output_sink() -> None:
    """Mark the cached output sink stale; re-resolved lazily on next playback.

    Called on audio device (re)connect. Lazy (not an eager re-resolve here)
    avoids opening an extra pulsectl session — each one costs a PCM
    reset/restore round-trip — right in the watcher's hot path.
    """
    _state.output_sink_dirty = True


def resolve_output_sink(
    output_spec: str | None, retries: int = 5, retry_delay: float = 1.0
) -> str | None:
    """Look up and cache the PipeWire sink name for output_spec.

    Returns the sink node name for use as pw-play --target, or None when
    output_spec is 'pipewire'/'default'/None (let PipeWire route normally).
    Retries up to `retries` times with `retry_delay` seconds between attempts
    to survive the startup race where WirePlumber hasn't finished initializing
    the USB device when the first pulsectl connection is opened.
    """
    _state.output_spec = output_spec
    if not output_spec or output_spec.lower() in ("pipewire", "default"):
        _state.output_sink = None
        return None
    auto = is_auto_spec(output_spec)
    needle = output_spec.lower()
    for attempt in range(retries):
        with pulse_session("alexa-sink-lookup") as pulse:
            for s in pulse.sink_list():
                if auto:
                    if s.name.startswith(USB_SINK_PREFIX):
                        _state.output_sink = s.name
                        return s.name
                elif needle in s.description.lower() or needle in s.name.lower():
                    _state.output_sink = s.name
                    return s.name
        if attempt < retries - 1:
            logger.debug(
                f"resolve_output_sink: sink {output_spec!r} not ready, "
                f"retrying in {retry_delay}s ({attempt + 1}/{retries})"
            )
            time.sleep(retry_delay)
    logger.warning(f"resolve_output_sink: no sink found for {output_spec!r}")
    _state.output_sink = None
    return None


def get_input_gain() -> float:
    return _state.input_gain


def get_software_input_gain() -> float:
    if _state.hw_gain_applied:
        return 1.0
    return _state.input_gain


def get_post_playback_ms() -> int:
    return _state.post_playback_ms


def get_tone_preroll_ms() -> int:
    return _state.tone_preroll_ms


def get_sample_rates() -> dict[str, int]:
    return _state.samplerate


def get_default_card_name() -> str:
    return _state.default_card_name


def _restore_hw_pcm(card: int | None = None) -> None:
    """Restore ALSA hardware PCM to 100% after any pulsectl interaction.

    Resolves the ALSA card dynamically based on the configured card_name, unless `card` is explicitly passed
    (for test overrides). When no matching card is connected the call is a no-op.
    """
    if card is None:
        card_name = get_default_card_name()
        if not card_name:
            return  # quietly skip, no card configured
        result = _find_alsa_card(card_name)
        if result is None:
            logger.debug(f"_restore_hw_pcm: no {card_name} found, skipping")
            return
        card_index, _ = result
    else:
        card_index = card
    try:
        # Playback control name varies by hardware: PCM (original NewPie),
        # 'Playback Volume' (NewPie 32) — try in order until one succeeds.
        for control in ("PCM", "Playback Volume"):
            result = subprocess.run(
                ["amixer", "-c", str(card_index), "sset", control, "100%"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            if result.returncode == 0:
                break
    except FileNotFoundError:
        logger.warning("_restore_hw_pcm: amixer not installed; cannot restore PCM")
    except subprocess.TimeoutExpired:
        logger.warning(
            "_restore_hw_pcm: amixer timed out after 5s (card %s) — skipping",
            card_index,
        )


@contextmanager
def pulse_session(name: str):
    """Open a pulsectl connection that always restores the NewPie PCM on exit.

    Opening any ``pulsectl.Pulse()`` connection makes pipewire-pulse re-init the
    ALSA device, resetting the NewPie's hardware PCM mixer to 0% (see the audio
    notes in CLAUDE.md). This wrapper guarantees ``_restore_hw_pcm()`` runs on
    exit — even when the body raises — so the "never open Pulse() without
    restoring right after" rule is enforced structurally rather than by
    convention. Always prefer this over a bare ``pulsectl.Pulse(...)``.
    """
    pulse = pulsectl.Pulse(name)
    try:
        yield pulse
    finally:
        try:
            pulse.close()
        finally:
            _restore_hw_pcm()


def find_pipewire_device():
    """Return the sounddevice index for the PipeWire ALSA device."""
    import sounddevice as sd

    return next(
        (i for i, d in enumerate(sd.query_devices()) if d["name"] == "pipewire"),
        None,
    )


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
        f"Audio device not found: {name_or_index!r} — run 'serena-audio --list' to see available devices"
    )


def device_from_env(key: str) -> int | None:
    """Return the sounddevice index for INPUT_DEVICE or OUTPUT_DEVICE, or None if unset."""
    val = os.environ.get(key, "").strip()
    if not val:
        return None
    return resolve_device(val)


def _spec_matches(
    spec: str | None, name: str, description: str, usb_prefix: str
) -> bool:
    """True when a sink/source matches the device spec ('auto' → any USB node)."""
    if is_auto_spec(spec):
        return name.startswith(usb_prefix)
    needle = (spec or "").lower()
    return needle in description.lower() or needle in name.lower()


def set_pipewire_defaults(input_spec: str | None, output_spec: str | None):
    """Set PipeWire default source/sink by matching INPUT_DEVICE/OUTPUT_DEVICE name."""
    with pulse_session("alexa-routing") as pulse:
        if output_spec and output_spec.lower() not in ("pipewire", "default"):
            match = next(
                (
                    s
                    for s in pulse.sink_list()
                    if _spec_matches(
                        output_spec, s.name, s.description, USB_SINK_PREFIX
                    )
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
            match = next(
                (
                    s
                    for s in pulse.source_list()
                    if "monitor" not in s.name
                    and _spec_matches(
                        input_spec, s.name, s.description, USB_SOURCE_PREFIX
                    )
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
    """Return the pulsectl card object matching the spec (name, desc, or index).

    A spec of 'auto' matches the first USB audio card, whatever its vendor.
    """
    if not spec:
        spec = _state.default_card_name
    if not spec:
        return None

    if is_auto_spec(spec):
        for card in pulse.card_list():
            if card.proplist.get("device.bus", "").lower() == "usb":
                return card
        return None

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
    via ``get_output_volume()``.  The value is also read by ``pw-play`` for
    WAV files and by the TTS engine.
    """
    _state.output_volume = volume
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
    updating the software-scaling value used by the STT capture pipeline.
    """
    with _input_gain_lock:
        hw_ok = False
        source_name = _find_pipewire_source(input_spec)
        if source_name is not None:
            _restore_hw_pcm()
            pct = int(max(0.0, gain) * 100)
            try:
                result = subprocess.run(
                    ["pactl", "set-source-volume", source_name, f"{pct}%"],
                    capture_output=True,
                    check=False,
                    timeout=5,
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "pactl set-source-volume timed out after 5s on %s — "
                    "falling back to software scaling",
                    source_name,
                )
                result = None
            if result is not None and result.returncode == 0:
                logger.info(f"Mic gain set to {pct}% on {source_name} (OS level)")
                hw_ok = True
            elif result is not None:
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

        _state.input_gain = max(0.0, gain)
        _state.hw_gain_applied = hw_ok

        if not hw_ok:
            logger.warning(
                f"Input gain {gain:.0%} applied in software (CPU overhead, clipping risk)"
            )


def enforce_audio_state(
    pulse: pulsectl.Pulse, input_spec: str | None = None, output_spec: str | None = None
) -> tuple[bool, str]:
    """Find configured card, force profile if it exists, and set default sink/source."""
    is_virtual = (output_spec or "").lower() in ("pipewire", "default") or (
        output_spec is None and _state.default_card_name is None
    )

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
    is_virtual = (output_spec or "").lower() in ("pipewire", "default") or (
        output_spec is None and _state.default_card_name is None
    )

    with pulse_session("alexa-check") as pulse:
        ok, conn = enforce_audio_state(pulse, input_spec, output_spec)
        if not ok:
            print(
                f"ERROR: Audio device {output_spec or _state.default_card_name!r} not found."
            )
            return False, "unknown"

        if is_virtual:
            return True, "virtual"

        info = pulse.server_info()
        sinks = {s.name: s for s in pulse.sink_list()}
        sources = {s.name: s for s in pulse.source_list()}

        default_sink = sinks.get(info.default_sink_name)
        default_source = sources.get(info.default_source_name)

        target_out = output_spec or _state.default_card_name
        if not default_sink or not _spec_matches(
            target_out, default_sink.name, default_sink.description, USB_SINK_PREFIX
        ):
            print(
                f"WARNING: Default sink is not the expected device (got: {info.default_sink_name})"
            )
            ok = False

        target_in = input_spec or _state.default_card_name
        if not default_source or not _spec_matches(
            target_in,
            default_source.name,
            default_source.description,
            USB_SOURCE_PREFIX,
        ):
            print(
                f"WARNING: Default source is not the expected device (got: {info.default_source_name})"
            )
            ok = False

    return ok, conn


def _find_alsa_card(needle: str) -> tuple[int, str] | None:
    """Return (card_index, card_id) for first ALSA card whose id or description contains needle.

    Checks the short card ID first (e.g. "NewPie"), then falls back to the full
    description in /proc/asound/cards (e.g. "USB-Audio - NewPie 32") so that devices
    whose ALSA id is truncated/sanitized (e.g. "N32") are still found.

    A needle of "auto" returns the first USB sound card (USB cards expose a
    usbid file in /proc/asound/cardN/), whatever its vendor.
    """
    if is_auto_spec(needle):
        for entry in sorted(os.listdir("/proc/asound")):
            if not entry.startswith("card") or not entry[4:].isdigit():
                continue
            if os.path.isfile(f"/proc/asound/{entry}/usbid"):
                try:
                    with open(f"/proc/asound/{entry}/id") as f:
                        return int(entry[4:]), f.read().strip()
                except OSError:
                    pass
        return None

    needle_lower = needle.lower()
    for entry in os.listdir("/proc/asound"):
        if not entry.startswith("card"):
            continue
        try:
            with open(f"/proc/asound/{entry}/id") as f:
                card_id = f.read().strip()
            if needle_lower in card_id.lower():
                return int(entry[4:]), card_id
        except OSError:
            pass
    # Fallback: search full card descriptions in /proc/asound/cards
    try:
        with open("/proc/asound/cards") as f:
            for line in f:
                if needle_lower not in line.lower():
                    continue
                parts = line.split()
                if parts and parts[0].isdigit():
                    card_index = int(parts[0])
                    try:
                        with open(f"/proc/asound/card{card_index}/id") as fid:
                            return card_index, fid.read().strip()
                    except OSError:
                        pass
    except OSError:
        pass
    return None


def _find_pipewire_source(input_spec: str | None, retries: int = 3) -> str | None:
    """Return the PipeWire source name matching input_spec, or None if not found.

    Retries up to `retries` times with a short sleep because opening a pulsectl
    connection triggers pipewire-pulse to re-initialise the ALSA device, which
    can transiently hide sources from the source list.
    """
    for attempt in range(retries):
        with pulse_session("alexa-source-lookup") as pulse:
            if input_spec is None:
                info = pulse.server_info()
                if info.default_source_name:
                    return info.default_source_name
            else:
                for s in pulse.source_list():
                    if "monitor" in s.name:
                        continue
                    if _spec_matches(
                        input_spec, s.name, s.description, USB_SOURCE_PREFIX
                    ):
                        return s.name
        if attempt < retries - 1:
            time.sleep(0.5)
    return None
