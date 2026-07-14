#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sys

# ---------------------------------------------------------------------------
# Sibling imports and re-exports for 100% backward compatibility
# ---------------------------------------------------------------------------
from alexa_custom.audio_hw import (
    _STATE_FILE,
    configure,
    get_output_volume,
    get_input_gain,
    get_software_input_gain,
    get_post_playback_ms,
    get_tone_preroll_ms,
    get_sample_rates,
    get_default_card_name,
    _restore_hw_pcm,
    pulse_session,
    find_pipewire_device,
    resolve_device,
    device_from_env,
    set_pipewire_defaults,
    find_alexa_card,
    detect_connection,
    set_output_volume,
    set_input_gain,
    enforce_audio_state,
    check_newpie_ready,
    _find_alsa_card,
)
from alexa_custom.audio_diagnostic import (
    _UDEV_PATH,
    list_devices,
    list_env_devices,
    _usb_ids_for_alsa_card,
    setup_audio,
    speakerphone,
    audio_doctor,
)
from alexa_custom.audio_ops import (
    _PW_PLAY,
    _playback_active,
    _audio_lock,
    _playback_level,
    get_playback_level,
    set_playback_level,
    is_playback_active,
    _play_array,
    _play_raw,
    play_wav_file,
    record_wav_file,
    play_tone,
    play_beep,
    play_wake_beep,
    play_wake_beep_async,
    play_timeout_beep,
    play_call_start,
    play_call_end,
)
from alexa_custom.audio_watcher import AudioWatcher

__all__ = [
    "_UDEV_PATH",
    "_STATE_FILE",
    "configure",
    "get_output_volume",
    "get_input_gain",
    "get_software_input_gain",
    "get_post_playback_ms",
    "get_tone_preroll_ms",
    "get_sample_rates",
    "get_default_card_name",
    "_restore_hw_pcm",
    "pulse_session",
    "find_pipewire_device",
    "resolve_device",
    "device_from_env",
    "set_pipewire_defaults",
    "find_alexa_card",
    "detect_connection",
    "set_output_volume",
    "set_input_gain",
    "enforce_audio_state",
    "check_newpie_ready",
    "_find_alsa_card",
    "list_devices",
    "list_env_devices",
    "_usb_ids_for_alsa_card",
    "setup_audio",
    "audio_doctor",
    "speakerphone",
    "_PW_PLAY",
    "_playback_active",
    "_audio_lock",
    "_playback_level",
    "get_playback_level",
    "set_playback_level",
    "is_playback_active",
    "_play_array",
    "_play_raw",
    "play_wav_file",
    "record_wav_file",
    "play_tone",
    "play_beep",
    "play_wake_beep",
    "play_wake_beep_async",
    "play_timeout_beep",
    "play_call_start",
    "play_call_end",
    "AudioWatcher",
]

logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--list", "-l", "list"):
        list_devices()
    else:
        speakerphone()


def main_devices():
    list_env_devices()


def main_doctor():
    """Entry point for `serena-audio-doctor`: exit non-zero if any check fails."""
    sys.exit(audio_doctor())


def main_test():
    import tempfile
    import logging as _logging
    from alexa_custom.tts import init_engine, get_engine
    from alexa_custom.config import load_config

    _logging.basicConfig(
        level=_logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    print("--- Audio System Test ---")

    from alexa_custom.config import load_secrets

    load_secrets("conf/secrets.yaml")
    config = load_config("conf/config.yaml")

    input_spec = config.audio.input_device if config else None
    output_spec = config.audio.output_device if config else None

    from alexa_custom.audio_hw import resolve_output_sink

    try:
        set_pipewire_defaults(input_spec, output_spec)
    except Exception as e:
        print(f"WARNING: Could not set PipeWire defaults: {e}")

    resolve_output_sink(output_spec)

    if config and config.audio.output_volume > 0:
        with pulse_session("alexa-test") as pulse:
            set_output_volume(pulse, output_spec, config.audio.output_volume)

    print("1. Playing tone...")
    play_tone("info")

    print("2. TTS: Asking for name...")
    if config:
        init_engine(
            backend_type=config.tts.backend,
            voice=config.tts.voice,
            preroll_ms=config.tts.preroll_ms,
        )
    else:
        init_engine(backend_type="piper")

    get_engine().say("Ciao, come ti chiami?")

    from alexa_custom.stt_gating import resolve_capture_source

    capture_source, capture_channels = resolve_capture_source(input_spec)
    print(
        f"3. Recording 5 seconds of audio (source={capture_source or 'default'}, ch={capture_channels})..."
    )
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = f.name

    try:
        print("   [RECORDING NOW - SPEAK INTO MICROPHONE]")
        record_wav_file(tmp_wav, 5.0, capture_source, capture_channels)
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
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        main_doctor()
    else:
        main()
