import argparse
import asyncio
import json
import logging
import math
import os
import struct
import sys
import time
from pathlib import Path

from livekit import rtc
from openai import AsyncOpenAI

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ai-agent")

SAMPLE_RATE = 48000
TTS_SAMPLE_RATE = 22050
VOSK_RATE = 16000
CHANNELS = 1


async def _process_audio(
    track: rtc.Track,
    identity: str,
    vosk_model,
    stop_event: asyncio.Event,
    audio_source: rtc.AudioSource,
    llm: AsyncOpenAI,
    tts_voice,
    conversation: list,
):
    from vosk import KaldiRecognizer

    stream = rtc.AudioStream(track)
    rec = KaldiRecognizer(vosk_model, VOSK_RATE)
    rec.SetWords(True)

    logger.info(f"Audio stream started for {identity}")
    async for event in stream:
        if stop_event.is_set():
            break

        pcm = _frame_to_pcm(event.frame, VOSK_RATE)
        if not pcm:
            continue

        if rec.AcceptWaveform(pcm):
            result = json.loads(rec.Result())
            text = result.get("text", "").strip()
            if text:
                logger.info(f"STT: {text}")
                await _handle_llm(text, llm, tts_voice, audio_source, conversation)
        else:
            partial = json.loads(rec.PartialResult())
            ptext = partial.get("partial", "").strip()
            if ptext:
                logger.debug(f"Partial: {ptext}")

    logger.info(f"Audio stream ended for {identity}")


async def _handle_llm(
    text: str,
    llm: AsyncOpenAI,
    tts_voice,
    audio_source: rtc.AudioSource,
    conversation: list,
):
    conversation.append({"role": "user", "content": text})
    logger.info(f"LLM → {text}")
    try:
        response = await llm.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=conversation,
            temperature=0.7,
            max_tokens=200,
        )
        reply = response.choices[0].message.content.strip()
        logger.info(f"LLM ← {reply}")
        conversation.append({"role": "assistant", "content": reply})
        if len(conversation) > 12:
            conversation[:] = [conversation[0]] + conversation[-10:]
        await _speak(reply, tts_voice, audio_source)
    except Exception as e:
        logger.error(f"Groq error: {e}")
        await _speak("Mi dispiace, non ho capito. Puoi ripetere?", tts_voice, audio_source)


async def _speak(text: str, tts_voice, audio_source: rtc.AudioSource):
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


def _synthesize(text: str, tts_voice) -> bytes:
    from piper import SynthesisConfig

    cfg = SynthesisConfig()
    chunks = []
    for chunk in tts_voice.synthesize(text, cfg):
        chunks.append(chunk.audio_int16_bytes)
    return b"".join(chunks)


async def _play_pcm(pcm: bytes, audio_source: rtc.AudioSource):
    frame_size = SAMPLE_RATE // 50
    ratio = SAMPLE_RATE / TTS_SAMPLE_RATE

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
        chunk = data[offset:offset + frame_size * 2]
        samples_count = len(chunk) // 2
        if samples_count == 0:
            break
        frame = rtc.AudioFrame(
            data=chunk,
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
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
        samples = struct.unpack(f"<{len(data)//2}h", data)
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
    num_samples = int(SAMPLE_RATE * duration)
    samples = [int(32767 * 0.2 * math.sin(2 * math.pi * 660 * i / SAMPLE_RATE)) for i in range(num_samples)]
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

    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        logger.error("GROQ_API_KEY not set")
        sys.exit(1)
    llm = AsyncOpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")

    logger.info("Loading Vosk model...")
    from vosk import Model
    vosk_model = Model(str(Path("models/it")))
    logger.info("Vosk model loaded")

    logger.info("Loading Piper voice...")
    from piper import PiperVoice, SynthesisConfig
    tts_voice = PiperVoice.load(str(Path("models/piper/it_IT-paola-medium.onnx")), use_cuda=False)
    logger.info("Piper voice loaded")

    conversation = [
        {"role": "system", "content": "Sei un assistente vocale utile. Rispondi in modo conciso, massimo due frasi. Parla sempre in italiano."},
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
            asyncio.create_task(_process_audio(track, participant.identity, vosk_model, stop, audio_source, llm, tts_voice, conversation))

    logger.info("Connecting...")
    audio_source = rtc.AudioSource(SAMPLE_RATE, CHANNELS)
    await room.connect(args.url, args.token)
    logger.info(f"Connected as {room.local_participant.identity}")

    track = rtc.LocalAudioTrack.create_audio_track("agent-voice", audio_source)
    opts = rtc.TrackPublishOptions()
    opts.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, opts)
    logger.info("Audio track published")

    await _play_beep(audio_source)
    await _speak("Ciao, sono il tuo assistente. Come posso aiutarti?", tts_voice, audio_source)
    logger.info("Waiting for user speech...")

    try:
        await asyncio.wait_for(stop.wait(), timeout=180)
    except asyncio.TimeoutError:
        logger.info("Timeout reached")
    finally:
        await room.disconnect()
        logger.info("Disconnected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"Agent crashed: {e}")
