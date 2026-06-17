import argparse
import asyncio
import json
import logging
import math
import os
import struct
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import httpx
from livekit import rtc
from livekit.api import AccessToken, VideoGrants, LiveKitAPI, DeleteRoomRequest

from alexa_custom.llm import OpenAIClient

_IPC_DIR = Path.home() / ".local" / "share" / "alexa-agent"
_REQUEST_FILE = _IPC_DIR / "request.json"
_STATUS_FILE = _IPC_DIR / "status.json"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ai-agent")


@dataclass
class AgentConfig:
    llm_model: str = "glm-5.2"
    llm_base_url: str = "https://ai.nahcrof.com"
    llm_timeout: float = 30.0
    temperature: float = 0.3
    max_tokens: int = 80
    system_prompt: str = (
        "Sei un assistente vocale utile. Rispondi in modo chiaro e naturale. "
        "Parla sempre in italiano. "
        "Non terminare la conversazione finché l'utente non dice 'disconnetti'. "
        "Se l'utente ti descrive un problema o un malore, "
        "fornisci consigli utili e rassicuranti su cosa fare nell'immediato."
    )
    vosk_model_path: str = "models/it"
    tts_voice_path: str = "models/piper/it_IT-paola-medium.onnx"
    sample_rate: int = 48000
    tts_sample_rate: int = 22050
    vosk_rate: int = 16000
    channels: int = 1
    tts_cooldown_ms: int = 300
    rms_threshold: float = 0.001
    debug_audio_every_n: int = 50
    vad_silence_ms: int = 400
    vad_min_speech_ms: int = 150
    session_timeout: float = 0.0  # 0 = no timeout
    tts_length_scale: float = 1.3
    grammar_phrases: list[str] | None = None

    def llm_extra(self) -> dict:
        return {"temperature": self.temperature, "max_tokens": self.max_tokens}


config = AgentConfig()

_DEFAULT_GRAMMAR = [
    "si", "no", "non lo so", "forse", "ok", "okay", "va bene",
    "non sto bene", "ho bisogno di aiuto", "chiama aiuto", "aiutami",
    "mi sento male", "sto male", "chiama un medico", "chiama l'ambulanza",
    "emergenza", "aiuto",
    "disconnetti", "arrivederci", "grazie", "ciao",
    "buongiorno", "buonasera", "buonanotte",
    "ripeti", "non ho capito", "puoi ripetere", "puoi parlare piu lentamente",
    "stai bene", "come stai", "bene", "male", "cosi cosi",
    "qual e il mio nome", "che ore sono", "che giorno e oggi",
    "apri il browser", "chiama stefano",
    "voglio parlare con un operatore", "parla con un operatore",
]


def _build_grammar(phrases: list[str] | None) -> str | None:
    if not phrases:
        return None
    normalized = sorted(set(p.lower().strip() for p in phrases if p.strip()))
    tokens = normalized + ["[unk]"]
    logger.info("agent grammar: %d tokens", len(tokens))
    return json.dumps(tokens)


_SENTENCE_END = frozenset(".!?")

_tts_cooldown_until: float = 0.0
_caregiver_notified: bool = False

_DISTRESS_PHRASES = frozenset({
    "non sto bene",
    "ho bisogno di aiuto",
    "chiama aiuto",
    "aiutami",
    "mi sento male",
    "sto male",
    "chiama un medico",
    "chiama l'ambulanza",
    "emergenza",
    "no",
})


async def _notify_caregiver(room_name: str, room_url: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("CAREGIVER_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("caregiver: TELEGRAM_BOT_TOKEN or CAREGIVER_CHAT_ID not set")
        return False

    api_key = os.environ.get("LIVEKIT_API_KEY", "")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "")
    if not api_key or not api_secret:
        logger.warning("caregiver: LIVEKIT_API_KEY or LIVEKIT_API_SECRET not set")
        return False

    caregiver_identity = f"caregiver-{int(time.time())}"
    caregiver_token = (
        AccessToken(api_key, api_secret)
        .with_identity(caregiver_identity)
        .with_name("Caregiver")
        .with_grants(VideoGrants(room_join=True, room=room_name, can_publish_sources=["microphone"]))
        .to_jwt()
    )
    params = urllib.parse.urlencode({"liveKitUrl": room_url, "token": caregiver_token})
    join_url = f"https://meet.livekit.io/custom/?{params}"

    text = (
        f"🚨 Richiesta di aiuto!\n\n"
        f"L'utente ha bisogno di assistenza.\n"
        f"Clicca per entrare nella stanza LiveKit:\n{join_url}"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text})
            resp.raise_for_status()
        logger.info("caregiver: Telegram notification sent")
        return True
    except Exception as e:
        logger.error(f"caregiver: Telegram notification failed: {e}")
        return False


def _is_distress(text: str) -> bool:
    norm = text.lower().strip().rstrip(".!?")
    for phrase in _DISTRESS_PHRASES:
        if phrase in norm:
            return True
    return False


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


async def _close_room(room_name: str):
    """Delete the LiveKit room to disconnect all participants."""
    key = os.environ.get("LIVEKIT_API_KEY")
    secret = os.environ.get("LIVEKIT_API_SECRET")
    host = os.environ.get("LIVEKIT_URL")
    if not key or not secret or not host:
        logger.warning("_close_room: missing LiveKit credentials")
        return
    try:
        async with LiveKitAPI() as api:
            await api.room.delete_room(DeleteRoomRequest(room=room_name))
        logger.info("Room %s deleted", room_name)
    except Exception as e:
        logger.warning("_close_room: failed to delete room %s: %s", room_name, e)


async def _check_disconnect(text: str, tts_voice, audio_source, stop_event, room_name: str = "") -> bool:
    norm = text.lower().strip().rstrip(".!?")
    if "disconnetti" in norm:
        await _speak("Arrivederci.", tts_voice, audio_source)
        stop_event.set()
        asyncio.create_task(_close_room(room_name))
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
    room_url: str,
    vosk_grammar: str | None = None,
):
    global _caregiver_notified
    from vosk import KaldiRecognizer

    stream = rtc.AudioStream(track)
    rec = (
        KaldiRecognizer(vosk_model, config.vosk_rate, vosk_grammar)
        if vosk_grammar
        else KaldiRecognizer(vosk_model, config.vosk_rate)
    )
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
                    if await _check_disconnect(text, tts_voice, audio_source, stop_event, room.name or ""):
                        return
                    if _is_distress(text) and not _caregiver_notified:
                        _caregiver_notified = True
                        asyncio.create_task(
                            _notify_caregiver(room.name or "", room_url)
                        )
                        await _speak("Ho chiamato aiuto. Dimmi cosa è successo.", tts_voice, audio_source)
                        conversation.append({"role": "assistant", "content": "Ho chiamato aiuto. Dimmi cosa è successo."})
                        _speech_ms = 0.0
                        rec.Reset()
                        continue
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
                if await _check_disconnect(text, tts_voice, audio_source, stop_event, room.name or ""):
                    return
                if _is_distress(text) and not _caregiver_notified:
                    _caregiver_notified = True
                    asyncio.create_task(
                        _notify_caregiver(room.name or "", room_url)
                    )
                    await _speak("Ho chiamato aiuto. Dimmi cosa è successo.", tts_voice, audio_source)
                    conversation.append({"role": "assistant", "content": "Ho chiamato aiuto. Dimmi cosa è successo."})
                else:
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
    cfg.length_scale = config.tts_length_scale
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


async def run_session(
    room_name: str,
    token: str,
    room_url: str,
    llm: OpenAIClient,
    vosk_model,
    tts_voice,
    vosk_grammar: str | None = None,
):
    """Connect to a LiveKit room and handle a conversation session."""
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
        if p.identity.startswith("caregiver-"):
            logger.info("Caregiver joined — agent leaving room")
            async def _leave():
                await _speak("Arrivederci, il caregiver è arrivato. Passo la linea.", tts_voice, audio_source)
                stop.set()
            asyncio.create_task(_leave())

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
                    room_url,
                    vosk_grammar=vosk_grammar,
                )
            )

    logger.info("Connecting...")
    audio_source = rtc.AudioSource(config.sample_rate, config.channels)
    await room.connect(room_url, token)
    logger.info(f"Connected as {room.local_participant.identity}")

    track = rtc.LocalAudioTrack.create_audio_track("agent-voice", audio_source)
    opts = rtc.TrackPublishOptions()
    opts.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, opts)
    logger.info("Audio track published")

    await _play_beep(audio_source)
    await _speak(
        "Ciao, sono il tuo assistente. Stai bene?", tts_voice, audio_source
    )
    logger.info("Waiting for user speech...")

    try:
        await stop.wait()
    finally:
        await room.disconnect()
        logger.info("Disconnected")


def _write_status(state: str, room: str = ""):
    _IPC_DIR.mkdir(parents=True, exist_ok=True)
    _STATUS_FILE.write_text(json.dumps({"state": state, "room": room}))


async def _wait_for_request() -> dict | None:
    """Poll for request.json — returns parsed dict or None."""
    if _REQUEST_FILE.exists():
        try:
            data = json.loads(_REQUEST_FILE.read_text())
            _REQUEST_FILE.unlink(missing_ok=True)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Invalid request file: %s", e)
            _REQUEST_FILE.unlink(missing_ok=True)
    return None


async def daemon_main():
    """Persistent daemon: load models once, then loop waiting for session requests."""
    _write_status("idle")

    api_key = os.environ.get("CROF_AI_API_KEY")
    if not api_key:
        logger.error("CROF_AI_API_KEY not set")
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

    vosk_grammar = _build_grammar(config.grammar_phrases or _DEFAULT_GRAMMAR)
    if vosk_grammar:
        logger.info("Using constrained grammar for STT")

    logger.info("Agent daemon ready, waiting for sessions...")

    while True:
        request = await _wait_for_request()
        if request is not None:
            room = request.get("room", "")
            token = request.get("token", "")
            url = request.get("url", "")
            if not room or not token or not url:
                logger.warning("Invalid request — missing fields")
                _write_status("idle")
                await asyncio.sleep(0.5)
                continue

            logger.info("Starting session in room %s", room)
            _write_status("connecting", room)
            try:
                await run_session(room, token, url, llm, vosk_model, tts_voice, vosk_grammar=vosk_grammar)
            except Exception as e:
                logger.exception("Session failed: %s", e)
            _write_status("idle")
        else:
            await asyncio.sleep(0.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="Run as persistent daemon")
    parser.add_argument("--room", help="Room name (single session)")
    parser.add_argument("--token", help="JWT token (single session)")
    parser.add_argument("--url", default=os.environ.get("LIVEKIT_URL"))
    args = parser.parse_args()

    if args.daemon:
        logger.info("Starting agent daemon...")
        try:
            asyncio.run(daemon_main())
        except Exception as e:
            logger.exception("Agent daemon crashed: %s", e)
            sys.exit(1)
    else:
        if not args.room or not args.token:
            logger.error("--room and --token required unless --daemon is used")
            sys.exit(1)

        api_key = os.environ.get("CROF_AI_API_KEY")
        if not api_key:
            logger.error("CROF_AI_API_KEY not set")
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

        vosk_grammar = _build_grammar(config.grammar_phrases or _DEFAULT_GRAMMAR)
        if vosk_grammar:
            logger.info("Using constrained grammar for STT")

        try:
            asyncio.run(run_session(args.room, args.token, args.url or "", llm, vosk_model, tts_voice, vosk_grammar=vosk_grammar))
        except Exception as e:
            logger.exception("Agent session failed: %s", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
