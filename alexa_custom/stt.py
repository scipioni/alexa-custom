from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import select
import subprocess
import threading
import time
import unicodedata
from abc import ABC, abstractmethod
from typing import Awaitable, Callable, TYPE_CHECKING

import numpy as np
import vosk

if TYPE_CHECKING:
    from alexa_custom.mqtt import MQTTClient

from alexa_custom.actions import TelegramClient, dispatch, match_trigger
from alexa_custom.audio import is_playback_active, play_timeout_beep, play_wake_beep
from alexa_custom.config import ActionsConfig, Trigger, WakeWordGroup

logger = logging.getLogger(__name__)

_CHUNK = 4096
_MODEL_PATH = os.environ.get("VOSK_MODEL_PATH", "models/it")
_STT_COOLDOWN = 1.0
_SHERPA_MODEL_PATH = os.environ.get("SHERPA_ONNX_PATH", "models/sherpa-onnx")

# Energy VAD for sherpa-onnx stage-1 wake-word detection.
# After speech is heard, if RMS stays below this threshold for
# _STAGE1_VAD_SILENCE_MS, finalize() is called immediately without waiting
# for sherpa's own endpoint (which requires 1.2 s of silence by default).
# Override via environment variables to tune for your microphone / room.
_STAGE1_VAD_SILENCE_MS = int(os.environ.get("STT_STAGE1_VAD_SILENCE_MS", "500"))
_STAGE1_RMS_THRESHOLD = float(os.environ.get("STT_STAGE1_RMS_THRESHOLD", "0.02"))
# Minimum sustained speech (ms above threshold) required before the silence
# timer can fire.  Prevents brief background noise bursts from prematurely
# finalizing sherpa's stream and discarding a partial wake word.
_STAGE1_MIN_SPEECH_MS = int(os.environ.get("STT_STAGE1_MIN_SPEECH_MS", "300"))


class STTBackend(ABC):
    @abstractmethod
    def accept_waveform(self, data: bytes) -> bool:
        pass

    @abstractmethod
    def text(self) -> str:
        pass

    @abstractmethod
    def partial_text(self) -> str:
        pass

    @abstractmethod
    def reset(self) -> None:
        pass

    def finalize(self) -> str:
        """Force-complete the current utterance and return recognized text.

        Called after the command window closes (deadline or VAD exit) to flush
        any audio that was still being decoded.  The default delegates to
        ``text()``; backends that need extra work (e.g. sherpa-onnx
        ``input_finished()``) override this.
        """
        return self.text()


class VoskSTT(STTBackend):
    def __init__(
        self, model: vosk.Model, sample_rate: int = 16000, grammar: str | None = None
    ):
        self._model = model
        self._sample_rate = sample_rate
        self._grammar = grammar
        self._rec = (
            vosk.KaldiRecognizer(model, sample_rate, grammar)
            if grammar
            else vosk.KaldiRecognizer(model, sample_rate)
        )

    @property
    def model(self) -> vosk.Model:
        return self._model

    def accept_waveform(self, data: bytes) -> bool:
        return self._rec.AcceptWaveform(data)

    def text(self) -> str:
        return json.loads(self._rec.Result()).get("text", "").strip()

    def partial_text(self) -> str:
        return json.loads(self._rec.PartialResult()).get("partial", "").strip()

    def reset(self) -> None:
        self._rec.Reset()

    def recreate(self, grammar: str | None = None) -> None:
        if grammar != self._grammar:
            self._grammar = grammar
            self._rec = (
                vosk.KaldiRecognizer(self._model, self._sample_rate, grammar)
                if grammar
                else vosk.KaldiRecognizer(self._model, self._sample_rate)
            )


class SherpaOnnxSTT(STTBackend):
    def __init__(self, model_dir: str = _SHERPA_MODEL_PATH):
        import sherpa_onnx

        if not os.path.isdir(model_dir):
            raise RuntimeError(
                f"sherpa-onnx model not found at {model_dir!r}. Run 'alexa-setup --sherpa-onnx' to download it."
            )
        tokens = os.path.join(model_dir, "tokens.txt")
        encoder = os.path.join(model_dir, "encoder.onnx")
        decoder = os.path.join(model_dir, "decoder.onnx")
        joiner = os.path.join(model_dir, "joiner.onnx")
        encoder_int8 = os.path.join(model_dir, "encoder.int8.onnx")
        decoder_int8 = os.path.join(model_dir, "decoder.int8.onnx")
        joiner_int8 = os.path.join(model_dir, "joiner.int8.onnx")

        if os.path.exists(joiner) or os.path.exists(joiner_int8):
            self._delegate = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=tokens,
                encoder=encoder_int8 if os.path.exists(encoder_int8) else encoder,
                decoder=decoder_int8 if os.path.exists(decoder_int8) else decoder,
                joiner=joiner_int8 if os.path.exists(joiner_int8) else joiner,
                num_threads=4,
                decoding_method="greedy_search",
                sample_rate=16000,
                feature_dim=80,
                provider="cpu",
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=2.4,
                rule2_min_trailing_silence=1.2,
                rule3_min_utterance_length=20,
            )
        else:
            self._delegate = sherpa_onnx.OnlineRecognizer.from_paraformer(
                tokens=tokens,
                encoder=encoder,
                decoder=decoder,
            )
        self._stream = self._delegate.create_stream()

    def accept_waveform(self, data: bytes) -> bool:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        self._stream.accept_waveform(sample_rate=16000, waveform=samples)
        while self._delegate.is_ready(self._stream):
            self._delegate.decode_stream(self._stream)
        return self._delegate.is_endpoint(self._stream)

    def text(self) -> str:
        result = self._delegate.get_result(self._stream)
        return result.strip() if isinstance(result, str) else result.text.strip()

    def partial_text(self) -> str:
        result = self._delegate.get_result(self._stream)
        return result.strip() if isinstance(result, str) else result.text.strip()

    def finalize(self) -> str:
        """Force the transducer to emit its buffered output, then reset the stream."""
        try:
            self._stream.input_finished()
        except Exception:
            pass
        while self._delegate.is_ready(self._stream):
            self._delegate.decode_stream(self._stream)
        result = self._delegate.get_result(self._stream)
        text = result.strip() if isinstance(result, str) else result.text.strip()
        self._stream = self._delegate.create_stream()
        return text

    def reset(self) -> None:
        self._delegate.reset(self._stream)


def get_stt_backend(backend: str, model_path: str | None = None) -> STTBackend:
    if backend == "sherpa-onnx":
        return SherpaOnnxSTT(model_path or _SHERPA_MODEL_PATH)
    vosk_path = model_path or _MODEL_PATH
    return VoskSTT(_load_model(vosk_path))


# Once we have detected any speech, return as soon as the recognizer has been
# idle (no new partial / no new final) for this many ms. Trims 1-4s off every
# reply window vs. waiting for the full `timeout`. Override via env.
_VAD_SILENCE_MS = int(os.environ.get("STT_VAD_SILENCE_MS", "700"))


def normalize_text(text: str) -> str:
    """Lowercase and remove diacritics (e.g., 'sì' -> 'si')."""
    if not text:
        return ""
    # Normalize to NFD (decomposed) to separate diacritics from base characters
    nfd = unicodedata.normalize("NFD", text.lower())
    # Filter out non-spacing marks (Mn category)
    stripped = "".join(c for c in nfd if not unicodedata.combining(c))
    # Back to NFC (composed)
    return unicodedata.normalize("NFC", stripped).strip()


def resolve_capture_source(input_spec: str | None) -> tuple[str | None, int]:
    """Map INPUT_DEVICE value to a PipeWire source name and channel count via pactl."""
    channels = 1
    if not input_spec:
        return None, channels
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"], text=True, timeout=5
        )
        needle = input_spec.lower()
        source_name = None
        found = False
        for line in out.splitlines():
            if "Name: " in line:
                name = line.split(": ", 1)[1].strip()
                if needle in name.lower() and "monitor" not in name.lower():
                    source_name = name
                    found = True
                elif found:
                    # Moved past the matched source block without finding spec — return now.
                    return source_name, channels
            if found and "Sample Specification:" in line:
                # e.g. "s16le 2ch 48000Hz"
                for part in line.split():
                    if part.endswith("ch"):
                        try:
                            channels = int(part[:-2])
                        except ValueError:
                            pass
                return source_name, channels

        logger.warning(f"No PipeWire source matching {input_spec!r} — using default")
    except Exception as e:
        logger.warning(f"resolve_capture_source failed: {e} — using default")
    return None, channels


def start_capture(source: str | None, channels: int = 1) -> subprocess.Popen:
    """Start a low-latency recording process (parec)."""
    import shutil

    tool = shutil.which("parec")
    if not tool:
        tool = shutil.which("pw-record")
        if not tool:
            raise RuntimeError("Neither parec nor pw-record found on system")

    is_pw = "pw-record" in tool
    cmd = [
        tool,
        "--rate=16000",
        f"--channels={channels}",
        "--format=s16le" if not is_pw else "--format=s16",
    ]

    if is_pw:
        cmd.extend(["--media-type=audio", "--media-role=communication"])
        if source:
            cmd.append(f"--target={source}")
    else:
        # Crucial: very low latency helps 'parec' start flowing on PipeWire
        cmd.append("--latency-msec=1")
        if source:
            cmd.append(f"--device={source}")

    # bufsize=0 keeps proc.stdout as raw FileIO so os.read (used by _drain_pipe
    # and _read_with_timeout) and the wake-loop's proc.stdout.read() see the
    # same byte stream — no Python-side BufferedReader holding stale frames.
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
    )


def _load_model(model_path: str = _MODEL_PATH) -> vosk.Model:
    if not os.path.isdir(model_path):
        raise RuntimeError(
            f"Vosk model not found at {model_path!r}. Run 'alexa-setup' to download it."
        )
    vosk.SetLogLevel(-1)
    return vosk.Model(model_path)


def _phrases_to_grammar(phrases: list[str]) -> str:
    """Convert a list of phrases to a Vosk grammar JSON string."""
    return json.dumps(phrases + ["[unk]"])


def _grammar_json(groups: list[WakeWordGroup]) -> str:
    phrases = [p for g in groups for p in [g.word] + g.aliases]
    return _phrases_to_grammar(phrases)


def _build_alias_map(groups: list[WakeWordGroup]) -> dict[str, WakeWordGroup]:
    return {
        normalize_text(phrase): group
        for group in groups
        for phrase in [group.word] + group.aliases
    }


def _approx_wake_match(
    text: str,
    alias_map: dict[str, WakeWordGroup],
    threshold: float = 0.5,
) -> WakeWordGroup | None:
    """Fuzzy wake-word match for open-vocabulary backends (sherpa-onnx).

    Exact alias-map lookup first; if that misses, scores each phrase by the
    fraction of its significant words (len >= 3) that appear anywhere in the
    transcript.  Returns the best-scoring group if score >= threshold, else None.

    Example: phrase "ehi galileo", transcript "e il galileo"
      key words: ["ehi", "galileo"]  →  "galileo" in transcript → 0.5 → match
    """
    norm_text = normalize_text(text)

    if norm_text in alias_map:
        return alias_map[norm_text]

    text_words = set(norm_text.split())
    best_group: WakeWordGroup | None = None
    best_score = 0.0

    for norm_phrase, group in alias_map.items():
        phrase_words = [w for w in norm_phrase.split() if len(w) >= 3]
        if not phrase_words:
            phrase_words = norm_phrase.split()
        matched = sum(
            1 for pw in phrase_words
            if any(pw in tw or (len(tw) >= 3 and tw in pw) for tw in text_words)
        )
        score = matched / len(phrase_words)
        if score > best_score:
            best_score = score
            best_group = group

    return best_group if best_score >= threshold else None


def _resolve_triggers(group: WakeWordGroup, fallback: list[Trigger]) -> list[Trigger]:
    return group.triggers if group.triggers else fallback


def _rms_level(data: bytes) -> float:
    samples = np.frombuffer(data, dtype=np.int16)
    n = len(samples)
    if n == 0:
        return 0.0
    return float(np.linalg.norm(samples)) / (32768.0 * n**0.5)


def _read_with_timeout(stdout, nbytes: int, timeout: float) -> bytes:
    """Best-effort read of up to ``nbytes`` from ``stdout`` within ``timeout`` seconds.

    Returns b'' if nothing arrived in the window. Prevents the recognizer thread
    from hanging forever when parec stalls (USB unplug, sink reset, etc.).
    """
    if stdout is None:
        return b""
    fd = stdout.fileno()
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return b""
    try:
        return os.read(fd, nbytes)
    except OSError:
        return b""


def _drain_pipe(proc: subprocess.Popen, max_bytes: int = 1 << 20) -> int:
    """Non-blocking: discard any audio already buffered in the capture pipe.

    Used to wipe acoustic echo / stale frames accumulated while playback was
    holding STT gated, before we hand fresh audio to the recognizer.
    """
    if proc.stdout is None:
        return 0
    fd = proc.stdout.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    drained = 0
    try:
        while drained < max_bytes:
            try:
                chunk = os.read(fd, 8192)
            except BlockingIOError:
                break
            if not chunk:
                break
            drained += len(chunk)
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
    return drained


def _downmix_to_mono(data: bytes, channels: int) -> bytes:
    """Take the loudest signal across all channels to ensure mono-downmix is high-gain."""
    if channels <= 1:
        return data
    frame_bytes = channels * 2  # s16le: 2 bytes per sample
    data = data[: len(data) // frame_bytes * frame_bytes]  # align to frame boundary
    if not data:
        return b""
    samples = np.frombuffer(data, dtype=np.int16).reshape(-1, channels)
    # Use max absolute value across channels to avoid diluting the signal with empty jacks.
    idx = np.argmax(np.abs(samples), axis=1)
    mono = samples[np.arange(len(samples)), idx]
    return mono.tobytes()


def run_stt_worker(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    stt_ready_event: threading.Event | None = None,
) -> None:
    """Entry point for the STT daemon thread.

    ``config`` may be a bare ActionsConfig or a zero-argument callable that
    returns the current ActionsConfig.  The callable form allows the caller to
    supply a live getter so the STT loop picks up hot-reloaded config on the
    next capture-process restart.
    """
    _get_config: Callable[[], ActionsConfig]
    if callable(config) and not isinstance(config, ActionsConfig):
        _get_config = config  # type: ignore[assignment]
    else:

        def _get_config():
            return config  # type: ignore[return-value]

    input_spec = os.environ.get("INPUT_DEVICE", "").strip() or None
    source, channels = resolve_capture_source(input_spec)

    current_config = _get_config()
    logger.info(
        f"STT: wake words={[g.word for g in current_config.wake_words]}, "
        f"timeout={current_config.command_timeout}s, "
        f"source={source or 'default'} ({channels} ch), "
        f"stt_backend={current_config.stt_backend}"
    )

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    current_config = _get_config()
    try:
        t0 = time.monotonic()
        backend = get_stt_backend(
            current_config.stt_backend, current_config.stt_model_path
        )
        logger.info(f"STT backend loaded in {time.monotonic() - t0:.1f}s")
    except RuntimeError as e:
        logger.error(f"STT backend creation failed: {e}")
        return
    backend_key = (current_config.stt_backend, current_config.stt_model_path)

    _dispatch_loop = asyncio.new_event_loop()
    try:
        while not stop_event.is_set():
            current_config = _get_config()
            loop_fn = (
                _single_stage_loop
                if current_config.recognition_mode == "single-stage"
                else _recognition_loop
            )
            # Reload backend only when the config changes it
            new_backend_key = (current_config.stt_backend, current_config.stt_model_path)
            if new_backend_key != backend_key:
                try:
                    backend = get_stt_backend(
                        current_config.stt_backend, current_config.stt_model_path
                    )
                    backend_key = new_backend_key
                    logger.info("STT backend reloaded after config change")
                except RuntimeError as e:
                    logger.error(f"STT backend reload failed: {e}")
                    time.sleep(2)
                    continue
            proc: subprocess.Popen | None = None
            try:
                proc = start_capture(source, channels)
                if stt_ready_event is not None and not stt_ready_event.is_set():
                    stt_ready_event.set()
                    logger.info("STT ready — listening for wake words")
                loop_fn(
                    proc=proc,
                    channels=channels,
                    backend=backend,
                    config=current_config,
                    stop_event=stop_event,
                    telegram_client=telegram_client,
                    livekit_connect_fn=livekit_connect_fn,
                    livekit_connected_flag=livekit_connected_flag,
                    on_stt_event=on_stt_event,
                    mqtt_client=mqtt_client,
                    loop=loop,
                    dispatch_loop=_dispatch_loop,
                )
            except Exception as e:
                logger.error(f"STT error: {e}")
                time.sleep(2)
            finally:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        pass
    finally:
        _dispatch_loop.close()


def _extract_wake_command(
    text: str, alias_map: dict[str, WakeWordGroup], fuzzy: bool = False
) -> tuple[WakeWordGroup | None, str]:
    """Return (group, command) if text begins with a known wake phrase, else (None, '').

    With fuzzy=True (sherpa-onnx single-stage path) uses _approx_wake_match to
    handle open-vocabulary transcription noise around wake words.
    """
    norm_text = normalize_text(text)
    for norm_phrase, group in alias_map.items():
        if norm_text.startswith(norm_phrase):
            command = text.lower().replace(norm_phrase, "", 1).strip()
            return group, command
    if fuzzy:
        group = _approx_wake_match(text, alias_map)
        if group:
            # Best-effort command extraction: strip matching phrase words from text
            norm_phrase = normalize_text(group.word)
            command = norm_text
            for w in norm_phrase.split():
                command = command.replace(w, "", 1).strip()
            return group, command
    return None, ""


def capture_transcript(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    timeout: float,
    stop_event: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    flush_ms: int = 0,
    phrases: list[str] | None = None,
    start_after_playback: bool = False,
) -> str:
    """Capture audio for a set duration and return the transcribed text.

    If ``start_after_playback`` is True the deadline is (re-)initialised when
    the playback gate drops. This lets the caller launch capture in parallel
    with a TTS ``say()``: pipe frames produced during playback are discarded
    in-flight (no backlog), and the full ``timeout`` window starts the moment
    the TTS finishes.
    """
    # Drop any audio that piled up in the pipe while we were blocked elsewhere
    # (e.g., during the preceding TTS in handle_ask). This is the echo of the
    # assistant's own voice — feeding it to vosk produces doubled/mixed words.
    assert proc.stdout is not None
    drained = _drain_pipe(proc)
    if drained:
        logger.debug(f"Drained {drained} bytes of stale audio before capture")

    # Active flush: read and discard a fixed window after the drain, as a guard
    # against any echo tail that arrives after the playback flag is cleared.
    # parec emits s16le -> 2 bytes per sample.
    if flush_ms > 0:
        bytes_to_flush = int(16000 * channels * 2 * (flush_ms / 1000))
        proc.stdout.read(bytes_to_flush)

    grammar = _phrases_to_grammar(phrases) if phrases else None
    if isinstance(backend, VoskSTT):
        backend.recreate(grammar)
    else:
        backend.reset()
    deadline = time.monotonic() + timeout
    transcript_parts: list[str] = []
    was_playing = False
    last_partial = ""
    last_activity = time.monotonic()
    got_speech = False

    while not stop_event.is_set() and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        raw_data = _read_with_timeout(proc.stdout, _CHUNK * channels, min(remaining, 1.0))
        if not raw_data:
            if proc.poll() is not None:
                logger.warning("Capture pipe closed mid-listen (parec exited)")
                break
            continue

        if is_playback_active():
            was_playing = True
            continue

        if was_playing:
            # Just emerged from playback: discard pipe backlog and reset the
            # recognizer so partial state from before the echo doesn't surface.
            _drain_pipe(proc)
            backend.reset()
            was_playing = False
            if start_after_playback:
                # Restart the listen window now that the TTS is actually over.
                deadline = time.monotonic() + timeout
            last_partial = ""
            last_activity = time.monotonic()
            got_speech = False
            continue

        data = _downmix_to_mono(raw_data, channels)

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if backend.accept_waveform(data):
            text = backend.text()
            if text:
                logger.info(f"Capture match: '{text}'")
                if on_stt_event:
                    on_stt_event("partial", {"text": text})

                # Grammar mode: first finalised match wins — return immediately.
                if phrases:
                    return text

                transcript_parts.append(text)
                got_speech = True
                last_activity = time.monotonic()
                last_partial = ""
        else:
            partial = backend.partial_text()
            if partial != last_partial:
                last_partial = partial
                if partial:
                    got_speech = True
                    last_activity = time.monotonic()
                    if on_stt_event:
                        full = " ".join(transcript_parts + [partial])
                        on_stt_event("partial", {"text": full})

        # VAD endpoint: speech was heard, recognizer idle long enough → user done.
        if got_speech and (time.monotonic() - last_activity) * 1000 >= _VAD_SILENCE_MS:
            break

    # Flush whatever recognizer hadn't finalised yet (deadline path or VAD path).
    # finalize() calls input_finished() on sherpa-onnx so the transducer emits
    # buffered output even when the endpoint hasn't fired within the window.
    final_text = backend.finalize()
    if final_text:
        transcript_parts.append(final_text)

    return " ".join(transcript_parts).strip()


def _single_stage_loop(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: "MQTTClient | None" = None,
    loop: asyncio.AbstractEventLoop | None = None,
    dispatch_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Single-stage: full transcription always; wake word + command in one phrase."""
    cooldown_until = 0.0
    was_playing = False
    alias_map = _build_alias_map(config.wake_words)

    if on_stt_event:
        on_stt_event("listening", {"wake_words": [g.word for g in config.wake_words]})

    async def _listen_fn(
        timeout: float,
        flush_ms: int = 0,
        phrases: list[str] | None = None,
        start_after_playback: bool = False,
    ) -> str:
        # Emit event for UI to show we are listening for a reply
        if on_stt_event:
            on_stt_event("wake", {"word": "(reply)", "timeout": timeout})
        return await asyncio.to_thread(
            capture_transcript,
            proc,
            channels,
            backend,
            timeout,
            stop_event,
            on_stt_event,
            flush_ms=flush_ms,
            phrases=phrases,
            start_after_playback=start_after_playback,
        )

    assert proc.stdout is not None
    _stall_logged = False
    while not stop_event.is_set():
        # Adjust chunk size for multi-channel
        raw_data = _read_with_timeout(proc.stdout, _CHUNK * channels, 2.0)
        if not raw_data:
            if proc.poll() is not None:  # parec exited
                logger.warning(
                    "single-stage: parec process exited — restarting capture"
                )
                break
            if not _stall_logged:
                logger.debug("single-stage: read timeout (parec stall?) — waiting")
                _stall_logged = True
            continue  # read timeout — re-check stop_event
        _stall_logged = False

        if is_playback_active():
            was_playing = True
            continue

        if was_playing:
            logger.debug("single-stage: playback ended — draining pipe and resetting")
            _drain_pipe(proc)
            backend.reset()
            was_playing = False
            continue

        data = _downmix_to_mono(raw_data, channels)

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if on_stt_event:
                on_stt_event("gated", {})
            continue

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if time.monotonic() < cooldown_until:
            backend.reset()
            continue

        if not backend.accept_waveform(data):
            if on_stt_event:
                partial = backend.partial_text()
                if partial:
                    on_stt_event("transcribing", {"text": partial})
            continue

        text = backend.text()
        if not text:
            # Empty segment — resync to real-time audio.
            backlog = _drain_pipe(proc)
            if backlog:
                logger.debug(
                    f"single-stage: drained {backlog} backlog bytes after empty segment"
                )
            backend.reset()
            continue

        wake_group, command = _extract_wake_command(
            text, alias_map, fuzzy=not isinstance(backend, VoskSTT)
        )
        if wake_group is None:
            # Non-wake speech — resync to real-time audio.
            backlog = _drain_pipe(proc)
            if backlog:
                logger.debug(
                    f"single-stage: drained {backlog} backlog bytes after non-wake segment"
                )
            backend.reset()
            continue

        logger.info(f"Single-stage: wake='{wake_group.word}' command='{command}'")
        if on_stt_event:
            on_stt_event("wake", {"word": wake_group.word, "timeout": 0})

        try:
            play_wake_beep(config.wake_tone)
        except Exception as e:
            logger.debug(f"Wake beep failed: {e}")

        if not command:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": ""})
            _play_timeout()
            continue

        triggers = _resolve_triggers(wake_group, config.triggers)
        trigger = match_trigger(command, triggers)
        if trigger is None:
            if on_stt_event:
                on_stt_event("nomatch", {"transcript": command})
            _play_timeout()
            continue

        if on_stt_event:
            on_stt_event("matched", {"transcript": command, "trigger": trigger.phrase})

        connected = livekit_connected_flag.is_set()
        try:
            _dloop = dispatch_loop or asyncio.new_event_loop()
            _dloop.run_until_complete(
                dispatch(
                    trigger,
                    telegram_client,
                    livekit_connect_fn,
                    livekit_connected=connected,
                    listen_fn=_listen_fn,
                    on_stt_event=on_stt_event,
                )
            )
            # Drop pipe backlog accumulated during dispatch (TTS/ask audio)
            # and reset the recognizer so the next wake-word match starts clean.
            _drain_pipe(proc)
            backend.reset()
            # Restore UI state after dispatch/dialogue
            if on_stt_event:
                on_stt_event(
                    "listening", {"wake_words": [g.word for g in config.wake_words]}
                )
        except Exception as e:
            logger.error(f"Action dispatch failed: {e}")


def _recognition_loop(
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    dispatch_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    alias_map = _build_alias_map(config.wake_words)
    is_vosk = isinstance(backend, VoskSTT)
    if is_vosk:
        vosk_model = backend.model
        stage1 = vosk.KaldiRecognizer(
            vosk_model, 16000, _grammar_json(config.wake_words)
        )
        stage1.SetWords(True)
        display_rec = vosk.KaldiRecognizer(vosk_model, 16000) if on_stt_event else None
    else:
        stage1 = None
        display_rec = None
    cooldown_until = 0.0
    was_gated = False
    was_playing = False
    stage1_last_speech_t = 0.0   # for sherpa energy VAD
    stage1_speech_ms = 0.0       # accumulated ms above RMS threshold in current utterance

    if on_stt_event:
        on_stt_event("listening", {"wake_words": [g.word for g in config.wake_words]})

    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state", "idle", loop=loop
        )

    assert proc.stdout is not None
    _stall_logged = False
    while not stop_event.is_set():
        raw_data = _read_with_timeout(proc.stdout, _CHUNK * channels, 2.0)
        if not raw_data:
            if proc.poll() is not None:  # parec exited
                logger.warning("two-stage: parec process exited — restarting capture")
                break
            if not _stall_logged:
                logger.debug("two-stage: read timeout (parec stall?) — waiting")
                _stall_logged = True
            continue  # read timeout — re-check stop_event
        _stall_logged = False

        if is_playback_active():
            was_playing = True
            continue

        if was_playing:
            logger.debug("two-stage: playback ended — draining pipe and resetting")
            _drain_pipe(proc)
            if is_vosk:
                stage1.Reset()
                if display_rec is not None:
                    display_rec.Reset()
            else:
                backend.reset()
                stage1_last_speech_t = 0.0
                stage1_speech_ms = 0.0
            was_playing = False
            continue

        data = _downmix_to_mono(raw_data, channels)

        if livekit_connected_flag.is_set():
            cooldown_until = time.monotonic() + _STT_COOLDOWN
            if not was_gated:
                logger.info("STT gated (call active)")
                if on_stt_event:
                    on_stt_event("gated", {})
                if mqtt_client:
                    mqtt_client.publish_threadsafe(
                        f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                        "gated",
                        loop=loop,
                    )
                was_gated = True
            continue

        if on_stt_event:
            on_stt_event("level", {"mic": _rms_level(data)})

        if was_gated:
            logger.info("STT resumed (call ended)")
            was_gated = False
            if on_stt_event:
                on_stt_event(
                    "listening", {"wake_words": [g.word for g in config.wake_words]}
                )
            if mqtt_client:
                mqtt_client.publish_threadsafe(
                    f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                    "idle",
                    loop=loop,
                )

        if time.monotonic() < cooldown_until:
            if is_vosk:
                stage1.Reset()
                if display_rec:
                    display_rec.Reset()
            else:
                backend.reset()
                stage1_last_speech_t = 0.0
                stage1_speech_ms = 0.0
            continue

        if is_vosk:
            if display_rec is not None:
                display_rec.AcceptWaveform(data)
                partial = (
                    json.loads(display_rec.PartialResult()).get("partial", "").strip()
                )
                if partial:
                    on_stt_event("transcribing", {"text": partial})  # type: ignore[misc]

            if stage1.AcceptWaveform(data):
                result = json.loads(stage1.Result())
                text = result.get("text", "").strip()
                words = result.get("result", [])
                conf = words[0].get("conf", 0.0) if words else 0.0
                logger.debug(f"Stage1 result: {text!r} conf={conf:.2f}")
                norm_text = normalize_text(text)
                wake_match = alias_map.get(norm_text)
                if wake_match is not None and conf >= config.wake_confidence:
                    _wake_detected(
                        wake_group=wake_match,
                        proc=proc,
                        channels=channels,
                        backend=backend,
                        config=config,
                        stop_event=stop_event,
                        telegram_client=telegram_client,
                        livekit_connect_fn=livekit_connect_fn,
                        livekit_connected_flag=livekit_connected_flag,
                        on_stt_event=on_stt_event,
                        mqtt_client=mqtt_client,
                        loop=loop,
                        dispatch_loop=dispatch_loop,
                    )
                    logger.debug(
                        f"two-stage: dispatch returned — livekit_flag={livekit_connected_flag.is_set()} "
                        f"was_gated={was_gated} was_playing={was_playing}"
                    )
                    _drain_pipe(proc)
                    vosk_model = backend.model
                    stage1 = vosk.KaldiRecognizer(
                        vosk_model, 16000, _grammar_json(config.wake_words)
                    )
                    stage1.SetWords(True)
                    display_rec = (
                        vosk.KaldiRecognizer(vosk_model, 16000)
                        if on_stt_event
                        else None
                    )
                    if on_stt_event:
                        on_stt_event(
                            "listening",
                            {"wake_words": [g.word for g in config.wake_words]},
                        )
                    if mqtt_client:
                        mqtt_client.publish_threadsafe(
                            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                            "idle",
                            loop=loop,
                        )
                else:
                    backlog = _drain_pipe(proc)
                    if backlog:
                        logger.debug(
                            f"two-stage: drained {backlog} backlog bytes after segment"
                        )
                    stage1.Reset()
                    if display_rec is not None:
                        display_rec.Reset()
        else:
            # sherpa-onnx: open-vocabulary stage1 with energy VAD for low latency.
            # Track RMS per chunk; after _STAGE1_VAD_SILENCE_MS ms of silence
            # following speech, force-finalize instead of waiting for sherpa's
            # own endpoint (which requires rule2_min_trailing_silence = 1.2 s).
            rms = _rms_level(data)
            chunk_ms = len(data) / (16000 * 2) * 1000
            if rms > _STAGE1_RMS_THRESHOLD:
                stage1_last_speech_t = time.monotonic()
                stage1_speech_ms += chunk_ms

            vad_triggered = (
                stage1_speech_ms >= _STAGE1_MIN_SPEECH_MS
                and stage1_last_speech_t > 0
                and (time.monotonic() - stage1_last_speech_t) * 1000 >= _STAGE1_VAD_SILENCE_MS
            )
            endpoint_fired = backend.accept_waveform(data)

            if endpoint_fired or vad_triggered:
                if vad_triggered and not endpoint_fired:
                    text = backend.finalize().strip()
                    trigger_src = "vad"
                else:
                    text = backend.text().strip()
                    backend.reset()
                    trigger_src = "endpoint"
                stage1_last_speech_t = 0.0
                stage1_speech_ms = 0.0
                if text:
                    logger.debug(f"Stage1 result (sherpa/{trigger_src}): {text!r}")
                    wake_match = _approx_wake_match(text, alias_map)
                    if wake_match:
                        _wake_detected(
                            wake_group=wake_match,
                            proc=proc,
                            channels=channels,
                            backend=backend,
                            config=config,
                            stop_event=stop_event,
                            telegram_client=telegram_client,
                            livekit_connect_fn=livekit_connect_fn,
                            livekit_connected_flag=livekit_connected_flag,
                            on_stt_event=on_stt_event,
                            mqtt_client=mqtt_client,
                            loop=loop,
                            dispatch_loop=dispatch_loop,
                        )
                        _drain_pipe(proc)
                        stage1_last_speech_t = 0.0
                        stage1_speech_ms = 0.0
                        if on_stt_event:
                            on_stt_event(
                                "listening",
                                {"wake_words": [g.word for g in config.wake_words]},
                            )
                        if mqtt_client:
                            mqtt_client.publish_threadsafe(
                                f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
                                "idle",
                                loop=loop,
                            )
            else:
                partial = backend.partial_text().strip()
                if partial and on_stt_event:
                    on_stt_event("transcribing", {"text": partial})


def _wake_detected(
    wake_group: WakeWordGroup,
    proc: subprocess.Popen,
    channels: int,
    backend: STTBackend,
    config: ActionsConfig,
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    dispatch_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    logger.info(f"Wake word detected: '{wake_group.word}'")
    if on_stt_event:
        on_stt_event(
            "wake", {"word": wake_group.word, "timeout": config.command_timeout}
        )
    if mqtt_client:
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/state",
            "listening",
            loop=loop,
        )
    try:
        play_wake_beep(config.wake_tone)
    except Exception as e:
        logger.debug(f"Wake beep failed: {e}")

    transcript = capture_transcript(
        proc,
        channels,
        backend,
        config.command_timeout,
        stop_event,
        on_stt_event,
        flush_ms=300,
    )
    logger.info(f"Command transcript: '{transcript}'")

    if not transcript:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": ""})
        _play_timeout()
        return

    if mqtt_client:
        payload = json.dumps(
            {"text": transcript, "wake_word": wake_group.word, "timestamp": time.time()}
        )
        mqtt_client.publish_threadsafe(
            f"{mqtt_client.topic_prefix}/{mqtt_client.node_id}/command",
            payload,
            loop=loop,
        )

    triggers = _resolve_triggers(wake_group, config.triggers)
    trigger = match_trigger(transcript, triggers)
    if trigger is None:
        if on_stt_event:
            on_stt_event("nomatch", {"transcript": transcript})
        _play_timeout()
        return

    if on_stt_event:
        on_stt_event("matched", {"transcript": transcript, "trigger": trigger.phrase})

    async def _listen_fn(
        timeout: float,
        flush_ms: int = 0,
        phrases: list[str] | None = None,
        start_after_playback: bool = False,
    ) -> str:
        # Emit event for UI to show we are listening for a reply
        if on_stt_event:
            on_stt_event("wake", {"word": "(reply)", "timeout": timeout})
        return await asyncio.to_thread(
            capture_transcript,
            proc,
            channels,
            backend,
            timeout,
            stop_event,
            on_stt_event,
            flush_ms=flush_ms,
            phrases=phrases,
            start_after_playback=start_after_playback,
        )

    # Dispatch using the persistent loop (we're in a daemon thread, not async context)
    connected = livekit_connected_flag.is_set()
    try:
        _dloop = dispatch_loop or asyncio.new_event_loop()
        _dloop.run_until_complete(
            dispatch(
                trigger,
                telegram_client,
                livekit_connect_fn,
                livekit_connected=connected,
                listen_fn=_listen_fn,
                on_stt_event=on_stt_event,
            )
        )
    except Exception as e:
        logger.error(f"Action dispatch failed: {e}")


def _play_timeout() -> None:
    logger.info("Command window timeout or no match")
    try:
        play_timeout_beep()
    except Exception as e:
        logger.debug(f"Timeout beep failed: {e}")


def start_stt_thread(
    config: ActionsConfig | Callable[[], ActionsConfig],
    stop_event: threading.Event,
    telegram_client: TelegramClient,
    livekit_connect_fn: Callable[[], Awaitable[None]] | None,
    livekit_connected_flag: threading.Event,
    on_stt_event: Callable[[str, dict], None] | None = None,
    mqtt_client: MQTTClient | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    stt_ready_event: threading.Event | None = None,
) -> threading.Thread:
    t = threading.Thread(
        target=run_stt_worker,
        args=(
            config,
            stop_event,
            telegram_client,
            livekit_connect_fn,
            livekit_connected_flag,
            on_stt_event,
            mqtt_client,
            loop,
            stt_ready_event,
        ),
        daemon=True,
        name="stt",
    )
    t.start()
    return t
