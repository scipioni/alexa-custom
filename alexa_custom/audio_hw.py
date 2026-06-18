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
    input_gain: float = 1.0
    hw_gain_applied: bool = False


_state = _AudioState()

_pw_device_resolved = False
_pw_device_index: int | None = None
_STATE_FILE = "conf/state.yaml"


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

    resolve_output_sink(cfg.audio.output_device)


def get_output_volume() -> float:
    return _state.output_volume


def get_output_sink() -> str | None:
    return _state.output_sink


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
    if not output_spec or output_spec.lower() in ("pipewire", "default"):
        _state.output_sink = None
        return None
    needle = output_spec.lower()
    for attempt in range(retries):
        with pulse_session("alexa-sink-lookup") as pulse:
            for s in pulse.sink_list():
                if needle in s.description.lower() or needle in s.name.lower():
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
        subprocess.run(
            ["amixer", "-c", str(card_index), "sset", "PCM", "100%"],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("_restore_hw_pcm: amixer not installed; cannot restore PCM")


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
    with pulse_session("alexa-routing") as pulse:
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
        spec = _state.default_card_name
    if not spec:
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

        target_out = (output_spec or _state.default_card_name).lower()
        if not default_sink or (
            target_out not in default_sink.description.lower()
            and target_out not in default_sink.name.lower()
        ):
            print(
                f"WARNING: Default sink is not the expected device (got: {info.default_sink_name})"
            )
            ok = False

        target_in = (input_spec or _state.default_card_name).lower()
        if not default_source or (
            target_in not in default_source.description.lower()
            and target_in not in default_source.name.lower()
        ):
            print(
                f"WARNING: Default source is not the expected device (got: {info.default_source_name})"
            )
            ok = False

    return ok, conn


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
                needle = input_spec.lower()
                for s in pulse.source_list():
                    if "monitor" in s.name:
                        continue
                    if needle in s.description.lower() or needle in s.name.lower():
                        return s.name
        if attempt < retries - 1:
            time.sleep(0.5)
    return None
