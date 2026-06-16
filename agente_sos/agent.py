from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import struct
import time
from pathlib import Path

from livekit import rtc
from livekit.api import AccessToken, VideoGrants

from alexa_agent.llm import OpenAIClient
from agente_sos.config import SOSConfig
from agente_sos.notifier import SOSNotifier

logger = logging.getLogger(__name__)

_VOSK_RATE = 16000
_TTS_COOLDOWN_MS = 1000
_RMS_THRESHOLD = 0.001
_VAD_SILENCE_MS = 600
_VAD_MIN_SPEECH_MS = 150
_SAMPLE_RATE = 48000
_TTS_SAMPLE_RATE = 22050
_SENTENCE_END = frozenset(".!?")
_SYSTEM_PROMPT = (
    "Sei un assistente di emergenza. Rispondi in modo conciso, "
    "massimo 15 parole. Parla sempre in italiano."
)

_CONVERSATION_SYSTEM = (
    "Sei un assistente vocale amichevole. Rispondi in modo conciso, "
    "massimo 2 frasi. Parla sempre in italiano, sii naturale e utile."
)

_POSITIVE = frozenset({"sì", "si", "tutto bene", "ok", "okay", "bene", "tutto a posto", "va bene", "nessun problema"})
_NEGATIVE = frozenset({"no", "non", "aiuto", "chiama", "emergenza", "aiutami", "per favore", "ho bisogno"})


def _is_positive(text: str) -> bool:
    return any(text.startswith(p) or p in text for p in _POSITIVE)


def _is_negative(text: str) -> bool:
    return any(text.startswith(n) or n in text for n in _NEGATIVE)


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


class SOSAgent:
    def __init__(self, config: SOSConfig, notifier: SOSNotifier):
        self._config = config
        self._notifier = notifier
        self._llm: OpenAIClient | None = None
        self._vosk_model = None
        self._tts_voice = None
        self._stop = asyncio.Event()
        self._tts_cooldown_until: float = 0.0
        self._conversation: list[dict] = []
        self._session_timeout: float = 300.0  # 5 min max

    async def start(self):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            logger.error("GROQ_API_KEY not set")
            return
        self._llm = OpenAIClient(
            host=self._config.llm_base_url,
            api_key=api_key,
            timeout=self._config.llm_timeout,
        )
        await asyncio.to_thread(self._load_models)

    def _load_models(self):
        from vosk import Model
        from piper import PiperVoice

        logger.info("Loading Vosk model from %s", self._config.vosk_model_path)
        self._vosk_model = Model(str(Path(self._config.vosk_model_path)))
        logger.info("Loading Piper voice from %s", self._config.tts_voice_path)
        self._tts_voice = PiperVoice.load(str(Path(self._config.tts_voice_path)), use_cuda=False)

    def _generate_token(self, room: str) -> str:
        key = self._config.livekit_api_key
        secret = self._config.livekit_api_secret
        token = (
            AccessToken(key, secret)
            .with_identity(self._config.agent_identity)
            .with_grants(
                VideoGrants(
                    room_join=True,
                    room=room,
                    can_publish_sources=["microphone"],
                )
            )
            .to_jwt()
        )
        return token

    async def handle_room(self, room: str):
        logger.info("Handling SOS request for room: %s", room)
        self._stop.clear()

        token = self._generate_token(room)
        room_client = rtc.Room()
        audio_source: rtc.AudioSource | None = None
        connected = asyncio.Event()

        @room_client.on("participant_connected")
        def _on_join(participant):
            logger.info("Participant joined: %s", participant.identity)

        @room_client.on("participant_disconnected")
        def _on_leave(participant):
            logger.info("Participant left: %s", participant.identity)
            self._stop.set()

        @room_client.on("track_subscribed")
        def _on_track(track, pub, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                logger.info("Audio track from %s", participant.identity)
                asyncio.create_task(self._process_audio(track, participant.identity, room_client, audio_source))

        @room_client.on("connected")
        def _on_connected():
            connected.set()

        audio_source = rtc.AudioSource(_SAMPLE_RATE, 1)
        logger.info("Connecting to room %s", room)
        await room_client.connect(self._config.livekit_url, token)

        track = rtc.LocalAudioTrack.create_audio_track("agent-voice", audio_source)
        opts = rtc.TrackPublishOptions()
        opts.source = rtc.TrackSource.SOURCE_MICROPHONE
        await room_client.local_participant.publish_track(track, opts)
        logger.info("Audio track published")

        await self._speak("Tutto bene?", audio_source)

        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self._session_timeout)
        except asyncio.TimeoutError:
            logger.info("SOS session timed out after %.0fs", self._session_timeout)
        finally:
            await room_client.disconnect()
            logger.info("Disconnected from room %s", room)

    async def _process_audio(
        self,
        track: rtc.Track,
        identity: str,
        room: rtc.Room,
        audio_source: rtc.AudioSource | None,
    ):
        from vosk import KaldiRecognizer

        stream = rtc.AudioStream(track)
        rec = KaldiRecognizer(self._vosk_model, _VOSK_RATE)
        rec.SetWords(True)

        async for event in stream:
            if self._stop.is_set():
                break
            pcm = self._frame_to_pcm(event.frame)
            if not pcm:
                continue
            if time.monotonic() < self._tts_cooldown_until:
                continue
            if rec.AcceptWaveform(pcm):
                result = json.loads(rec.Result())
                text = result.get("text", "").strip()
                if text:
                    logger.info("User said: %s", text)
                    await self._handle_user_response(text, room, audio_source)

    def _frame_to_pcm(self, frame: rtc.AudioFrame) -> bytes | None:
        data = frame.data
        rate = frame.sample_rate
        channels = frame.num_channels
        if channels > 1:
            samples = struct.unpack(f"<{len(data) // 2}h", data)
            mono = samples[0::channels]
            data = struct.pack(f"<{len(mono)}h", *mono)
        if rate != _VOSK_RATE and len(data) > 0:
            import numpy as np

            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            ratio = _VOSK_RATE / rate
            new_len = int(len(arr) * ratio)
            resampled = np.interp(
                np.linspace(0, len(arr) - 1, new_len),
                np.arange(len(arr)),
                arr,
            ).astype(np.int16)
            return resampled.tobytes()
        return data

    async def _handle_user_response(
        self,
        text: str,
        room: rtc.Room,
        audio_source: rtc.AudioSource | None,
    ):
        if self._conversation:
            await self._handle_conversation_turn(text, room, audio_source)
            return

        normalized = text.lower().strip().rstrip(".!?")

        if _is_negative(normalized):
            await self._speak("Va bene, chiamo subito aiuto. Resti in linea.", audio_source)
            await asyncio.to_thread(self._notifier.call_for_help, room.name)
            await self._speak("Ho chiamato i soccorsi. Arriveranno presto.", audio_source)
            await asyncio.sleep(3)
            self._stop.set()
        elif _is_positive(normalized):
            self._conversation = [
                {"role": "system", "content": _CONVERSATION_SYSTEM},
            ]
            await self._speak("Come posso aiutarti?", audio_source)
        else:
            classifier = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"L'utente ha risposto: '{text}'. "
                 f"Ha detto sì (tutto bene) o no (ha bisogno di aiuto)? "
                 f"Rispondi solo 'SI' o 'NO'."},
            ]
            try:
                reply = ""
                async for token in self._llm.chat_stream(
                    classifier, self._config.llm_model, extra_body={"temperature": 0.1, "max_tokens": 10}
                ):
                    reply += token
                reply = reply.strip().upper()
                if reply.startswith("SI") or reply.startswith("SÌ"):
                    self._conversation = [
                        {"role": "system", "content": _CONVERSATION_SYSTEM},
                    ]
                    await self._speak("Come posso aiutarti?", audio_source)
                else:
                    await self._speak("Va bene, chiamo subito aiuto. Resti in linea.", audio_source)
                    await asyncio.to_thread(self._notifier.call_for_help, room.name)
                    await self._speak("Ho chiamato i soccorsi. Arriveranno presto.", audio_source)
                    await asyncio.sleep(3)
                    self._stop.set()
            except Exception as e:
                logger.error("LLM classification failed: %s", e)
                await self._speak("Non ho capito. Può ripetere?", audio_source)

    async def _handle_conversation_turn(
        self,
        text: str,
        room: rtc.Room,
        audio_source: rtc.AudioSource | None,
    ):
        goodbye = {"ciao", "arrivederci", "buona giornata", "grazie", "non ho bisogno", "va bene così"}
        norm = text.lower().strip().rstrip(".!?")
        if any(norm.startswith(g) or g in norm for g in goodbye):
            await self._speak("Di niente, buona giornata!", audio_source)
            await asyncio.sleep(2)
            self._stop.set()
            return

        self._conversation.append({"role": "user", "content": text})
        try:
            buf = ""
            full = ""
            async for token in self._llm.chat_stream(
                self._conversation, self._config.llm_model, extra_body={"temperature": 0.3, "max_tokens": 80}
            ):
                buf += token
                sentences, buf = _split_sentences(buf)
                for sentence in sentences:
                    full += sentence + " "
                    await self._speak(sentence.strip(), audio_source)
            remainder = buf.strip()
            if remainder:
                full += remainder
                await self._speak(remainder, audio_source)
            if full:
                self._conversation.append({"role": "assistant", "content": full.strip()})
                if len(self._conversation) > 12:
                    self._conversation[:] = [self._conversation[0]] + self._conversation[-10:]
        except Exception as e:
            logger.error("LLM conversation error: %s", e)
            await self._speak("Mi dispiace, non ho capito. Puoi ripetere?", audio_source)

    async def _speak(self, text: str, audio_source: rtc.AudioSource | None):
        if not audio_source:
            return
        self._tts_cooldown_until = time.monotonic() + _TTS_COOLDOWN_MS / 1000
        try:
            pcm = await asyncio.to_thread(self._synthesize, text)
            if not pcm:
                return
            await self._play_pcm(pcm, audio_source)
        except Exception as e:
            logger.exception("TTS error: %s", e)

    def _synthesize(self, text: str) -> bytes:
        from piper import SynthesisConfig

        cfg = SynthesisConfig()
        chunks = []
        for chunk in self._tts_voice.synthesize(text, cfg):
            chunks.append(chunk.audio_int16_bytes)
        return b"".join(chunks)

    async def _play_pcm(self, pcm: bytes, audio_source: rtc.AudioSource):
        frame_size = _SAMPLE_RATE // 50
        ratio = _SAMPLE_RATE / _TTS_SAMPLE_RATE

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
                sample_rate=_SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=samples_count,
            )
            await audio_source.capture_frame(frame)
            await asyncio.sleep(0.016)
            offset += len(chunk)
