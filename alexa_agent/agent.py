import argparse
import asyncio
import json
import logging
import math
import os
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from livekit import rtc

from alexa_custom.llm import OpenAIClient

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ai-agent")


@dataclass
class AgentConfig:
    llm_model: str = "llama-3.1-8b-instant"
    llm_base_url: str = "https://api.groq.com/openai"
    llm_timeout: float = 30.0
    temperature: float = 0.3
    max_tokens: int = 80
    system_prompt: str = (
        "Sei un assistente vocale utile. Rispondi in modo conciso, "
        "massimo una frase, al massimo 15 parole. Parla sempre in italiano."
    )
    vosk_model_path: str = "models/it"
    tts_voice_path: str = "models/piper/it_IT-paola-medium.onnx"
    sample_rate: int = 48000
    tts_sample_rate: int = 22050
    vosk_rate: int = 16000
    channels: int = 1
    tts_cooldown_ms: int = 1000
    rms_threshold: float = 0.001
    debug_audio_every_n: int = 50
    vad_silence_ms: int = 600
    vad_min_speech_ms: int = 150
    session_timeout: float = 0.0  # 0 = no timeout

    def llm_extra(self) -> dict:
        return {"temperature": self.temperature, "max_tokens": self.max_tokens}


config = AgentConfig()

_SENTENCE_END = frozenset(".!?")

_tts_cooldown_until: float = 0.0


def _compute_rms(data: bytes) -> float:
    if not data:
        return 0.0
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    if not samples:
        return 0.0
    mean_sq = sum(s * s for s in samples) / len(samples)
    return math.sqrt(mean_sq) / 32768.0


def _peak_sample(data: bytes) -> int:
    if not data:
        return 0
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    return max(abs(s) for s in samples) if samples else 0


async def _publish_chat(room: rtc.Room, text: str, generated: bool = False):
    import json as _json

    payload = _json.dumps(
        {
            "id": str(int(time.monotonic() * 1000)),
            "message": text,
            "timestamp": int(time.time()),
            "generated": generated,
        }
    )
    await room.local_participant.publish_data(payload, topic="chat")


async def _check_disconnect(text: str, tts_voice, audio_source, stop_event) -> bool:
    norm = text.lower().strip().rstrip(".!?")
    if "disconnetti" in norm:
        await _speak("Arrivederci.", tts_voice, audio_source)
        stop_event.set()
        return True
    return False


async def _process_audio(
    track: rtc.Track,
    identity: str,
    vosk_model,
    stop_event: asyncio.Event,
    audio_source: rtc.AudioSource,
    llm: OpenAIClient,
    tts_voice,
    conversation: list,
    room: rtc.Room,
):
    from vosk import KaldiRecognizer

    stream = rtc.AudioStream(track)
    rec = KaldiRecognizer(vosk_model, config.vosk_rate)
    rec.SetWords(True)

    logger.info(f"Audio stream started for {identity}")
    _frame_count = 0
    _last_speech_t = 0.0
    _speech_ms = 0.0
    async for event in stream:
        if stop_event.is_set():
            break

        pcm = _frame_to_pcm(event.frame, config.vosk_rate)
        if not pcm:
            continue

        if time.monotonic() < _tts_cooldown_until:
            continue

        _frame_count += 1
        rms = _compute_rms(pcm)
        if _frame_count % config.debug_audio_every_n == 0:
            peak = _peak_sample(pcm)
            logger.debug(
                f"Audio level: rms={rms:.4f} peak={peak} len={len(pcm)} "
                f"frame_rate={event.frame.sample_rate} ch={event.frame.num_channels}"
            )

        chunk_ms = len(pcm) / (config.vosk_rate * 2) * 1000
        if rms >= config.rms_threshold:
            _last_speech_t = time.monotonic()
            _speech_ms += chunk_ms
        else:
            self_silence = (
                time.monotonic() - _last_speech_t if _last_speech_t > 0 else 0.0
            )
            if (
                _speech_ms >= config.vad_min_speech_ms
                and self_silence * 1000 >= config.vad_silence_ms
                and not rec.AcceptWaveform(pcm)
            ):
                result = json.loads(rec.FinalResult())
                text = result.get("text", "").strip()
                if text:
                    logger.info(f"STT: {text}")
                    if _check_disconnect(text, tts_voice, audio_source, stop_event):
                        return
                    try:
                        await _publish_chat(room, text, generated=False)
                    except Exception as e:
                        logger.debug(f"Chat publish failed: {e}")
                    await _handle_llm(
                        text,
                        llm,
                        tts_voice,
                        audio_source,
                        conversation,
                        room,
                    )
                _speech_ms = 0.0
                rec.Reset()
                continue

        if rec.AcceptWaveform(pcm):
            result = json.loads(rec.Result())
            text = result.get("text", "").strip()
            if text:
                logger.info(f"STT: {text}")
                if _check_disconnect(text, tts_voice, audio_source, stop_event):
                    return
                try:
                    await _publish_chat(room, text, generated=False)
                except Exception as e:
                    logger.debug(f"Chat publish failed: {e}")
                await _handle_llm(
                    text,
                    llm,
                    tts_voice,
                    audio_source,
                    conversation,
                    room,
                )
            _speech_ms = 0.0
        else:
            partial = json.loads(rec.PartialResult())
            ptext = partial.get("partial", "").strip()
            if ptext:
                logger.debug(f"Partial: {ptext}")

    logger.info(f"Audio stream ended for {identity}")


def _split_sentences(buf: str) -> tuple[list[str], str]:
    sentences: list[str] = []
    start = 0
    for i, ch in enumerate(buf):
        if ch not in _SENTENCE_END:
            continue
        if ch == ".":
            prev = buf[i - 1] if i > 0 else ""
            end = i + 1
            while end < len(buf) and buf[end] in " \t":
                end += 1
            nxt = buf[end] if end < len(buf) else ""
            if prev.isdigit() or (nxt and not nxt.isupper()):
                continue
        else:
            end = i + 1
            while end < len(buf) and buf[end] in " \t":
                end += 1
        sentence = buf[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    return sentences, buf[start:]


async def _handle_llm(
    text: str,
    llm: OpenAIClient,
    tts_voice,
    audio_source: rtc.AudioSource,
    conversation: list,
    room: rtc.Room,
):
    conversation.append({"role": "user", "content": text})
    logger.info(f"LLM → {text}")
    try:
        buf = ""
        full_text = ""
        async for token in llm.chat_stream(
            conversation, config.llm_model, extra_body=config.llm_extra()
        ):
            buf += token
            sentences, buf = _split_sentences(buf)
            for sentence in sentences:
                full_text += sentence + " "
                await _speak(sentence, tts_voice, audio_source)
        remainder = buf.strip()
        if remainder:
            full_text += remainder
            await _speak(remainder, tts_voice, audio_source)
        reply = full_text.strip()
        logger.info(f"LLM ← {reply}")
        try:
            await _publish_chat(room, reply, generated=True)
        except Exception as e:
            logger.debug(f"Chat publish failed: {e}")
        conversation.append({"role": "assistant", "content": reply})
        if len(conversation) > 12:
            conversation[:] = [conversation[0]] + conversation[-10:]
    except Exception as e:
        logger.error(f"Groq error: {e}")
        await _speak(
            "Mi dispiace, non ho capito. Puoi ripetere?", tts_voice, audio_source
        )


async def _speak(text: str, tts_voice, audio_source: rtc.AudioSource):
    global _tts_cooldown_until
    if not audio_source:
        return
    logger.info(f"TTS: {text}")
    try:
        loop = asyncio.get_running_loop()
        pcm = await loop.run_in_executor(None, _synthesize, text, tts_voice)
        if not pcm:
            logger.warning("TTS produced no audio")
            return
        logger.info(f"TTS audio: {len(pcm)} bytes")
        await _play_pcm(pcm, audio_source)
        logger.info("TTS done")
    except Exception as e:
        logger.exception(f"TTS error: {e}")
    finally:
        _tts_cooldown_until = time.monotonic() + config.tts_cooldown_ms / 1000


def _synthesize(text: str, tts_voice) -> bytes:
    from piper import SynthesisConfig

    cfg = SynthesisConfig()
    chunks = []
    for chunk in tts_voice.synthesize(text, cfg):
        chunks.append(chunk.audio_int16_bytes)
    return b"".join(chunks)


async def _play_pcm(pcm: bytes, audio_source: rtc.AudioSource):
    frame_size = config.sample_rate // 50
    ratio = config.sample_rate / config.tts_sample_rate

    import numpy as np

    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    new_len = int(len(arr) * ratio)
    resampled = np.interp(
        np.linspace(0, len(arr) - 1, new_len),
        np.arange(len(arr)),
        arr,
    ).astype(np.int16)
    data = resampled.tobytes()

    offset = 0
    while offset < len(data):
        chunk = data[offset : offset + frame_size * 2]
        samples_count = len(chunk) // 2
        if samples_count == 0:
            break
        frame = rtc.AudioFrame(
            data=chunk,
            sample_rate=config.sample_rate,
            num_channels=config.channels,
            samples_per_channel=samples_count,
        )
        await audio_source.capture_frame(frame)
        await asyncio.sleep(0.016)
        offset += len(chunk)


def _frame_to_pcm(frame: rtc.AudioFrame, target_rate: int = 16000) -> bytes | None:
    data = frame.data
    rate = frame.sample_rate
    channels = frame.num_channels

    if channels > 1:
        samples = struct.unpack(f"<{len(data) // 2}h", data)
        mono = samples[0::channels]
        data = struct.pack(f"<{len(mono)}h", *mono)

    if rate != target_rate and len(data) > 0:
        import numpy as np

        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        ratio = target_rate / rate
        new_len = int(len(arr) * ratio)
        resampled = np.interp(
            np.linspace(0, len(arr) - 1, new_len),
            np.arange(len(arr)),
            arr,
        ).astype(np.int16)
        return resampled.tobytes()

    return data


async def _play_beep(source: rtc.AudioSource):
    duration = 0.3
    num_samples = int(config.sample_rate * duration)
    samples = [
        int(32767 * 0.2 * math.sin(2 * math.pi * 660 * i / config.sample_rate))
        for i in range(num_samples)
    ]
    pcm = struct.pack(f"<{num_samples}h", *samples)
    await _play_pcm(pcm, source)
    logger.info("Beep played")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--room", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--url", default=os.environ.get("LIVEKIT_URL"))
    args = parser.parse_args()

    logger.info(f"Starting agent for room {args.room}")

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY not set")
        sys.exit(1)
    llm = OpenAIClient(
        host=config.llm_base_url,
        api_key=api_key,
        timeout=config.llm_timeout,
    )

    logger.info("Loading Vosk model...")
    from vosk import Model

    vosk_model = Model(str(Path(config.vosk_model_path)))
    logger.info("Vosk model loaded")

    logger.info("Loading Piper voice...")
    from piper import PiperVoice

    tts_voice = PiperVoice.load(str(Path(config.tts_voice_path)), use_cuda=False)
    logger.info("Piper voice loaded")

    now = time.localtime()
    date_str = time.strftime("%A %d %B %Y, ore %H:%M", now)
    conversation = [
        {
            "role": "system",
            "content": f"{config.system_prompt} Data e ora corrente: {date_str}.",
        },
    ]

    room = rtc.Room()
    stop = asyncio.Event()
    audio_source: rtc.AudioSource | None = None

    @room.on("participant_connected")
    def on_join(p):
        logger.info(f"User joined: {p.identity}")

    @room.on("participant_disconnected")
    def on_leave(p):
        logger.info(f"User left: {p.identity}")
        stop.set()

    @room.on("track_subscribed")
    def on_track(track, pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"Audio track from {participant.identity}")
            asyncio.create_task(
                _process_audio(
                    track,
                    participant.identity,
                    vosk_model,
                    stop,
                    audio_source,
                    llm,
                    tts_voice,
                    conversation,
                    room,
                )
            )

    logger.info("Connecting...")
    audio_source = rtc.AudioSource(config.sample_rate, config.channels)
    await room.connect(args.url, args.token)
    logger.info(f"Connected as {room.local_participant.identity}")

    track = rtc.LocalAudioTrack.create_audio_track("agent-voice", audio_source)
    opts = rtc.TrackPublishOptions()
    opts.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, opts)
    logger.info("Audio track published")

    await _play_beep(audio_source)
    await _speak(
        "Ciao, sono il tuo assistente. Come posso aiutarti?", tts_voice, audio_source
    )
    logger.info("Waiting for user speech...")

    try:
        await stop.wait()
    finally:
        await room.disconnect()
        logger.info("Disconnected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"Agent crashed: {e}")
