"""Alexa-record utility."""

from __future__ import annotations

import argparse
import logging
import sys
import time

from alexa_custom.config import load_config, load_secrets
from alexa_custom.stt import (
    resolve_capture_source,
    start_capture,
    _CHUNK,
    _read_with_timeout,
    _downmix_to_mono,
    _apply_input_gain,
)
from alexa_custom.stt_backends import get_stt_backend
from alexa_custom.audio_hw import set_input_gain
from alexa_custom.audio import play_wake_beep
from alexa_custom.tts import init_engine, get_engine

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record speech at incremental gain levels and transcribe."
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10,
        help="Recording duration in seconds (default: 10)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="records.txt",
        help="Output file path (default: records.txt)",
    )
    parser.add_argument(
        "--text",
        type=str,
        default="ascolta assistente aiutami a chiamare aiuto perché sono in difficoltà",
        help="Reference text (default: 'ascolta assistente aiutami a chiamare aiuto perché sono in difficoltà')",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.ERROR, format="%(levelname)s %(name)s: %(message)s"
    )
    # Ensure all other loggers are quieted
    logging.getLogger().setLevel(logging.ERROR)
    for name in ["alexa_custom", "urllib3", "httpcore", "httpx", "livekit"]:
        logging.getLogger(name).setLevel(logging.ERROR)

    # Load configuration
    load_secrets("conf/secrets.yaml")
    config = load_config("conf/config.yaml")
    if config is None:
        print("Error: Could not load conf/config.yaml", file=sys.stderr)
        sys.exit(1)

    # Initialize TTS
    init_engine(
        backend_type=config.tts.backend,
        voice=config.tts.voice,
        preroll_ms=config.tts.preroll_ms,
    )
    tts_engine = get_engine()

    # Initialize STT
    _kws_keywords = [p for g in config.wake_words for p in [g.word] + g.aliases]
    stt_backend = get_stt_backend(config.stt.stage1, keywords=_kws_keywords)

    # Resolve capture source and channels
    source, channels = resolve_capture_source(config.audio.input_device)

    # Create/initialize the output file with reference text
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(f"testo riferimento: {args.text}\n")

    # Incremental gain loop
    input_gain = 0.1
    while input_gain <= 1.01:
        # Set input gain (hardware set first, software scaling fallback)
        set_input_gain(None, config.audio.input_device, input_gain)

        # TTS speech prompt
        msg = f"imposto il microfono a {input_gain:.1f}, prego registra testo per {args.duration} secondi"
        print(f"TTS: {msg}")
        tts_engine.say(msg)

        # Print reference text to stdout before playing tone
        print(f"--> {args.text}")
        sys.stdout.flush()

        # Play wake tone before activating STT
        play_wake_beep(config.recognition.wake_tone)

        # Give a very brief pause before recording to allow any hardware transition / echo to settle
        time.sleep(0.2)

        proc = start_capture(source, channels)
        try:
            assert proc.stdout is not None

            # Record for exactly the duration
            total_bytes = int(16000 * channels * 2 * args.duration)
            bytes_read = 0

            stt_backend.reset()
            chunk_size = _CHUNK * channels

            t_end = time.monotonic() + args.duration
            while bytes_read < total_bytes and time.monotonic() < t_end:
                to_read = min(chunk_size, total_bytes - bytes_read)
                raw_data = _read_with_timeout(proc.stdout, to_read, 0.5)
                if not raw_data:
                    if proc.poll() is not None:
                        break
                    continue
                bytes_read += len(raw_data)

                # Downmix and apply input gain
                processed_data = _apply_input_gain(_downmix_to_mono(raw_data, channels))

                stt_backend.accept_waveform(processed_data)

            spoken_text = stt_backend.finalize()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
                proc.wait()

        # Print to stdout and append to file
        print(f"{input_gain:.1f} {spoken_text}")
        sys.stdout.flush()

        with open(args.out, "a", encoding="utf-8") as f:
            f.write(f"{input_gain:.1f} {spoken_text}\n")

        # Increment input_gain
        input_gain += 0.1

    print("alexa-record completed successfully.")


if __name__ == "__main__":
    main()
