"""Long-lived LiveKit conversation agent daemon.

Always connected to the configured room, monitors for participants,
and handles conversations with Vosk STT -> CROF AI LLM.
TTS text is sent via data channel — the device renders it locally.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import numpy as np

from livekit.rtc import (
    AudioFrame,
    AudioSource,
    AudioStream,
    LocalAudioTrack,
    Room,
    TrackKind,
    TrackPublishOptions,
    TrackSource,
)

logger = logging.getLogger(__name__)

_TRIAGE_PROMPT = (
    "Sei Elsa, un'assistente simpatica e attenta. Parli italiano. "
    "Ogni risposta deve essere diversa — mai ripetere la stessa frase. "
    "Massimo 12 parole. Sii naturale e varia il tono.\n\n"
    "Il tuo lavoro: parlare con una persona anziana che potrebbe stare male. "
    "Chiedi come si sente, quali sintomi ha. "
    "Se i sintomi sono gravi (dolore al petto, difficoltà a respirare, "
    "svenimento, sangue abbondante) dì che chiami subito aiuto.\n\n"
    "Regole: "
    "1. Mai la stessa risposta due volte. "
    "2. Usa parole diverse: 'come va?', 'cosa succede?', 'mi dica', "
    "'che ha?', 'dimmi tutto', ecc. "
    "3. Sii breve ma varia.\n"
    "4. Prima di rispondere valuta l'urgenza e scrivi "
    "URGENZA:[NONE|LOW|MEDIUM|HIGH|CRITICAL] poi vai a capo."
)

_URGENCY_PROMPT = (
    "You are an emergency dispatcher. Assess medical urgency from the user's message.\n"
    "Reply with exactly ONE word: NONE, LOW, MEDIUM, HIGH, or CRITICAL.\n"
    "NONE = no medical issue\nLOW = minor complaint\n"
    "MEDIUM = needs attention\nHIGH = serious\nCRITICAL = life-threatening"
)

_END_PHRASES = {
    "arrivederci",
    "ciao",
    "grazie",
    "basta",
    "fine",
    "ci vediamo",
    "buongiorno",
    "buonasera",
    "a presto",
    "termina",
}


class GroqSTT:
    """Cloud STT via Groq Whisper API (OpenAI-compatible)."""

    BASE = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo"):
        self._api_key = api_key
        self._model = model

    async def transcribe(
        self, audio_data: bytes, sample_rate: int = 16000
    ) -> str | None:
        import io
        import wave

        import httpx

        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data)
        wav_buf.seek(0)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self.BASE,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": ("audio.wav", wav_buf, "audio/wav")},
                    data={"model": self._model, "language": "it"},
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "Groq STT error: HTTP %s %s", resp.status_code, resp.text[:200]
                    )
                    return None
                result = resp.json()
                text = result.get("text", "").strip()
                return text if text else None
        except Exception as e:
            logger.warning("Groq STT request failed: %s", e)
            return None


_MEDICAL_HOTWORDS = {
    "dolore": "dolore",
    "toracico": "toracico",
    "petto": "petto",
    "respirare": "respirare",
    "respiro": "respiro",
    "dispnea": "dispnea",
    "coscienza": "coscienza",
    "svenuto": "svenuto",
    "sanguino": "sanguino",
    "sangue": "sangue",
    "ferita": "ferita",
    "taglio": "taglio",
    "febbre": "febbre",
    "tosse": "tosse",
    "vertigini": "vertigini",
    "confuso": "confuso",
    "confusione": "confusione",
    "incidente": "incidente",
    "caduto": "caduto",
    "frattura": "frattura",
    "osso": "osso",
    "testa": "testa",
    "schiena": "schiena",
    "pancia": "pancia",
    "gamba": "gamba",
    "braccio": "braccio",
    "cuore": "cuore",
    "collo": "collo",
    "fianco": "fianco",
    "inguine": "inguine",
    "scottatura": "scottatura",
    "ustione": "ustione",
    "bruciore": "bruciore",
    "gonfiore": "gonfiore",
    "tumore": "tumore",
    "diabete": "diabete",
    "infarto": "infarto",
    "ictus": "ictus",
    "crampo": "crampo",
    "emicrania": "emicrania",
    "allergia": "allergia",
    "medicinale": "medicinale",
    "farmaco": "farmaco",
    "anticoagulante": "anticoagulante",
    "ospedale": "ospedale",
    "ambulanza": "ambulanza",
    "soccorso": "soccorso",
    "emergenza": "emergenza",
    "medico": "medico",
    "infermiere": "infermiere",
    "sintomo": "sintomo",
    "diagnosi": "diagnosi",
    "terapia": "terapia",
    "cura": "cura",
    "riposo": "riposo",
    "operazione": "operazione",
    "intervento": "intervento",
}

# Common mispronunciations / Vosk errors mapped to correct terms
_PHONETIC_FIXES = {
    "torassico": "toracico",
    "toracico": "toracico",
    "respirato": "respirare",
    "respirando": "respirare",
    "sfenuto": "svenuto",
    "sfenuta": "svenuta",
    "svenuta": "svenuta",
    "sanguinamento": "sanguinamento",
    "sanguina": "sanguina",
    "vertigine": "vertigini",
    "confussa": "confusa",
    "fratura": "frattura",
    "fratto": "frattura",
    "gamba rotta": "gamba rotta",
    "scotatura": "scottatura",
    "ustionato": "ustione",
    "gonfiato": "gonfiore",
    "gonfio": "gonfiore",
    "mal di testa": "mal di testa",
    "mal di pancia": "mal di pancia",
    "mal di schiena": "mal di schiena",
    "dolore al petto": "dolore al petto",
    "male al petto": "dolore al petto",
    "fame d'aria": "fame d'aria",
    "mancanza di respiro": "mancanza di respiro",
    "non respiro": "non respiro",
    "buco nero": "svenimento",
    "vista offuscata": "vista offuscata",
    "vedo doppio": "vista doppia",
    "parlare strano": "parlata strana",
    "braccio debole": "braccio debole",
    "faccia storta": "faccia storta",
    "bocca storta": "bocca storta",
}


def _correct_stt(text: str) -> str:
    """Apply fuzzy phonetic correction for Italian medical terms."""
    from rapidfuzz import fuzz

    words = text.lower().split()
    corrected = []
    for word in words:
        if word in _PHONETIC_FIXES:
            corrected.append(_PHONETIC_FIXES[word])
            continue
        best = word
        best_score = 0
        for hotword in _MEDICAL_HOTWORDS:
            score = fuzz.ratio(word, hotword, score_cutoff=70)
            if score > best_score:
                best = hotword
                best_score = score
        if best_score >= 75:
            corrected.append(_MEDICAL_HOTWORDS[best])
        else:
            corrected.append(word)
    result = " ".join(corrected)
    if result != text.lower():
        logger.debug("STT corrected: '%s' -> '%s'", text, result)
    return result


class AgentDaemon:
    def __init__(self, config, vosk_model=None, dispatch_cb=None):
        self._config = config
        self._dispatch_cb = dispatch_cb
        self._skill_text = self._load_skill()
        self._conversation_history: list[str] = []
        if vosk_model is None:
            from alexa_custom.stt import _MODEL_PATH
            from vosk import Model as _VoskModel

            model_path = str(_MODEL_PATH)
            if not os.path.isdir(model_path):
                raise FileNotFoundError(f"Vosk model not found: {model_path}")
            vosk_model = _VoskModel(model_path)
        self._vosk_model = vosk_model
        self._room: Room | None = None
        self._tts_source: AudioSource | None = None
        self._tts_busy = asyncio.Event()
        self._busy = asyncio.Event()
        self._stop = asyncio.Event()
        self._participant_identity: str | None = None
        self._device_identity: str | None = None
        self._responder_joined = asyncio.Event()
        self._llm_client = None
        self._groq_stt: GroqSTT | None = None
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if groq_key:
            self._groq_stt = GroqSTT(groq_key)

    def _load_skill(self) -> str:
        skill_path = Path("conf/skills/soccorso-anziani.yaml")
        if not skill_path.is_file():
            return ""
        try:
            import yaml as _yaml
        except ImportError:
            logger.warning("PyYAML not installed, skill disabled")
            return ""
        try:
            with open(skill_path) as f:
                skill = _yaml.safe_load(f)
            parts = [f"## {skill.get('name', 'skill')}\n{skill.get('description', '')}"]
            for s in skill.get("steps", []):
                parts.append(f"\n### Passo {s['step']} — {s['name']}")
                parts.append(s.get("description", ""))
                if "signals" in s:
                    parts.append("\nAllarme: " + "\n- ".join([""] + s["signals"]))
                if "response" in s:
                    parts.append(f"\nRisposta: {s['response']}")
                if "scenarios" in s:
                    for sc in s["scenarios"]:
                        parts.append(f"\nScenario {sc['name']}:")
                        for instr in sc.get("instructions", []):
                            parts.append(f"- {instr}")
            parts.append(
                "\n### Comunicazione\n"
                + "\n".join(f"- {c}" for c in skill.get("communication", []))
            )
            parts.append(
                "\n### Limiti\n" + "\n".join(f"- {x}" for x in skill.get("limits", []))
            )
            return "\n".join(parts)
        except Exception as e:
            logger.warning("Skill load failed: %s", e)
            return ""

    async def start(self) -> None:
        from livekit.api import AccessToken, VideoGrants

        api_key = os.environ.get("LIVEKIT_API_KEY", "")
        api_secret = os.environ.get("LIVEKIT_API_SECRET", "")
        livekit_url = os.environ.get("LIVEKIT_URL", "")
        room_name = os.environ.get("LIVEKIT_ROOM", "emergenza")
        if not all([api_key, api_secret, livekit_url]):
            logger.error("Agent: LiveKit credentials missing")
            return

        token = (
            AccessToken(api_key, api_secret)
            .with_identity("assistente-elsa")
            .with_name("Elsa")
            .with_grants(VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )

        self._room = Room()

        @self._room.on("participant_connected")
        def _on_join(participant):
            if (
                participant.identity != "assistente-elsa"
                and self._participant_identity is None
            ):
                self._participant_identity = participant.identity
                asyncio.create_task(self._handle_participant(participant))
            elif (
                participant.identity != "assistente-elsa"
                and participant.identity != self._device_identity
            ):
                self._responder_joined.set()

        @self._room.on("participant_disconnected")
        def _on_left(participant):
            if participant.identity == self._participant_identity:
                logger.info("Agent: participant left")
                self._participant_identity = None
                self._device_identity = None

        await self._room.connect(livekit_url, token)
        logger.info("Agent connected to room %s", room_name)
        await self._stop.wait()

    def stop(self):
        self._stop.set()
        if self._room:
            asyncio.create_task(self._room.disconnect())

    async def _say(self, text: str) -> None:
        """Send TTS text to device via data channel."""
        logger.info("TTS: '%s'", text)
        if not self._room:
            return
        try:
            dest = [self._device_identity] if self._device_identity else []
            await self._room.local_participant.publish_data(
                text,
                reliable=True,
                topic="tts",
                destination_identities=dest,
            )
        except Exception as e:
            logger.error("TTS data send error: %s", e)

    async def _say_room(self, text: str) -> None:
        """Publish one-shot TTS audio track to ALL room participants."""
        logger.info("Room TTS: '%s'", text)
        if not self._room or not text:
            return
        try:
            from alexa_custom.tts import PIPER_VOICES_DIR

            voice_path = PIPER_VOICES_DIR / "it_IT-paola-medium.onnx"
            if not voice_path.is_file():
                return
            from piper import PiperVoice

            voice = PiperVoice.load(str(voice_path))
            sr = 22050

            source = AudioSource(48000, 1)
            track = LocalAudioTrack.create_audio_track("agent-summary", source)
            opts = TrackPublishOptions(source=TrackSource.SOURCE_MICROPHONE)
            pub = await self._room.local_participant.publish_track(track, opts)
            await asyncio.sleep(0.5)

            for chunk in voice.synthesize(text):
                arr = getattr(chunk, "audio_int16_array", None)
                if arr is None:
                    raw = getattr(chunk, "audio_int16_bytes", None) or bytes(chunk)
                    arr = np.frombuffer(raw, dtype=np.int16)
                target_len = int(len(arr) * 48000 / sr)
                resampled = _resample_numpy(arr.astype(np.float32), target_len)
                if len(resampled) == 0:
                    continue
                frame = AudioFrame(
                    data=resampled.astype(np.int16).tobytes(),
                    sample_rate=48000,
                    num_channels=1,
                    samples_per_channel=len(resampled),
                )
                await source.capture_frame(frame)

            await asyncio.sleep(0.2)
            await self._room.local_participant.unpublish_track(pub.sid)
        except Exception as e:
            logger.warning("Room TTS error: %s", e)

    async def _wait_for_responder(self) -> None:
        """Wait for a responder to join. Resend Telegram link every 30s."""
        for attempt in range(5):
            self._responder_joined.clear()
            try:
                await asyncio.wait_for(self._responder_joined.wait(), timeout=30.0)
                if not self._conversation_history:
                    return
                summary = " ".join(
                    s.split(": ", 1)[-1] for s in self._conversation_history[-5:]
                )
                await self._say_room(f"Riassunto: {summary}")
                return
            except asyncio.TimeoutError:
                logger.warning(
                    "Agent: responder not joined after %ds", (attempt + 1) * 30
                )
                if self._dispatch_cb:
                    await self._dispatch_cb(
                        f"RIPETO: Nessuno è ancora entrato nella stanza di emergenza. "
                        f"Tentativo {attempt + 1}/5"
                    )
                await self._say(
                    "Non è ancora entrato nessuno. Stiamo ancora aspettando."
                )
        logger.error("Agent: no responder after max attempts")
        await self._say(
            "Mi dispiace, nessuno ha risposto. Chiamerò il numero di emergenza."
        )

    async def _handle_participant(self, participant) -> None:
        self._device_identity = participant.identity
        await self._say("Ciao, come stai? Posso aiutarti?")
        await asyncio.sleep(2.5)
        for pub in participant.track_publications.values():
            if pub.kind == TrackKind.KIND_AUDIO and pub.subscribed and pub.track:
                await self._run_conversation(pub.track)
                return

        future = asyncio.get_running_loop().create_future()

        @self._room.on("track_subscribed")
        def _on_track(track, publication, sub_participant):
            if (
                sub_participant.identity == participant.identity
                and track.kind == TrackKind.KIND_AUDIO
            ):
                if not future.done():
                    future.set_result(track)

        try:
            track = await asyncio.wait_for(future, timeout=30.0)
            await self._run_conversation(track)
        except asyncio.TimeoutError:
            logger.warning("Agent: no audio track within 30s")

    async def _run_conversation(self, track) -> None:
        stream = AudioStream(track)
        resampler = _AudioResampler()
        skill_text = self._skill_text
        if skill_text:
            system_prompt = _TRIAGE_PROMPT + "\n\n" + skill_text
        else:
            system_prompt = _TRIAGE_PROMPT
        llm_history = [{"role": "system", "content": system_prompt}]

        async def _drain():
            while self._busy.is_set():
                try:
                    await asyncio.wait_for(stream.__anext__(), timeout=0.5)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    return

        async def _echo_drain():
            await asyncio.sleep(1.0)

        if self._groq_stt:
            await self._run_groq_loop(
                stream, resampler, llm_history, _drain, _echo_drain
            )
        else:
            await self._run_vosk_loop(
                stream, resampler, llm_history, _drain, _echo_drain
            )

    async def _run_groq_loop(self, stream, resampler, llm_history, _drain, _echo_drain):
        """STT via Groq Whisper (cloud)."""
        audio_buf = bytearray()
        speech_start = 0.0
        last_speech = 0.0

        while self._participant_identity is not None:
            audio_buf.clear()
            speech_start = 0.0
            last_speech = 0.0
            try:
                async for frame in stream:
                    pcm16 = _frame_to_s16le(frame)
                    if pcm16 is None:
                        continue
                    down = resampler.feed(pcm16)
                    if down is None:
                        continue
                    rms = np.sqrt(np.mean(down.astype(np.float32) ** 2))
                    now = time.monotonic()

                    if rms >= 20:
                        if speech_start == 0.0:
                            speech_start = now
                            logger.info(
                                "Groq: speech START at %.1f (rms=%.1f)", now, rms
                            )
                        last_speech = now
                        audio_buf.extend(down.tobytes())
                        if now - speech_start > 5.0:
                            logger.info(
                                "Groq: max duration %.0fs, sending %dB",
                                now - speech_start,
                                len(audio_buf),
                            )
                            text = await self._groq_stt.transcribe(bytes(audio_buf))
                            speech_start = 0.0
                            if text and len(text.split()) >= 2:
                                if not await self._process_stt_text(
                                    text, llm_history, _drain, _echo_drain
                                ):
                                    return
                                resampler = _AudioResampler()
                                break
                            continue
                    elif speech_start > 0.0:
                        silence = now - last_speech
                        if silence > 1.0:
                            if len(audio_buf) < 3200:
                                logger.info(
                                    "Groq: buffer too small (%dB), restart",
                                    len(audio_buf),
                                )
                                speech_start = 0.0
                                continue
                            logger.info(
                                "Groq: silence %.1fs, buffer=%dB, sending...",
                                silence,
                                len(audio_buf),
                            )
                            text = await self._groq_stt.transcribe(bytes(audio_buf))
                            speech_start = 0.0
                            if not text or len(text.split()) < 2:
                                logger.debug("Groq: no/short text: '%s'", text)
                                break
                            if not await self._process_stt_text(
                                text, llm_history, _drain, _echo_drain
                            ):
                                return
                            resampler = _AudioResampler()
                            break
            except StopAsyncIteration:
                break
            except Exception as e:
                logger.error("Groq STT error: %s", e)
                break
        logger.info("Agent: conversation ended")

    async def _process_stt_text(
        self, text: str, llm_history, _drain, _echo_drain
    ) -> bool:
        """Process transcribed text. Returns False if conversation should end."""
        logger.info("STT: '%s'", text)
        if text.lower() in _END_PHRASES or any(p in text.lower() for p in _END_PHRASES):
            await self._say("Arrivederci, stammi bene!")
            return False

        self._busy.set()
        drainer = asyncio.create_task(_drain())

        urgency, reply = await self._combined_chat(text, llm_history)
        if urgency in ("HIGH", "CRITICAL"):
            logger.critical("Agent: emergency assessed %s", urgency)
            if self._dispatch_cb:
                await self._dispatch_cb(f"URGENCY:{urgency}:{text}")
            await self._say("Ho capito, chiamo subito aiuto. Come sta adesso?")
            asyncio.create_task(self._wait_for_responder())
        else:
            await self._say(reply)
        await _echo_drain()

        self._busy.clear()
        await drainer
        return True

    async def _run_vosk_loop(self, stream, resampler, llm_history, _drain, _echo_drain):
        from vosk import KaldiRecognizer

        while self._participant_identity is not None:
            rec = KaldiRecognizer(self._vosk_model, 16000)
            rec.SetWords(True)
            rec.SetPartialWords(True)
            rec.SetMaxAlternatives(3)
            speech_timeout = 0.0
            last_partial = ""
            try:
                async for frame in stream:
                    pcm16 = _frame_to_s16le(frame)
                    if pcm16 is None:
                        continue
                    down = resampler.feed(pcm16)
                    if down is None:
                        continue
                    rms = np.sqrt(np.mean(down.astype(np.float32) ** 2))
                    if rms < 20 and speech_timeout == 0.0:
                        continue
                    if rec.AcceptWaveform(down.tobytes()):
                        result = json.loads(rec.Result())
                        if "alternatives" in result:
                            best = max(
                                result["alternatives"],
                                key=lambda a: a.get("confidence", 0),
                            )
                            text = best.get("text", "").strip()
                        else:
                            text = result.get("text", "").strip()
                        if not text or len(text.split()) < 2:
                            speech_timeout = 0.0
                            continue
                        text = _correct_stt(text)
                        logger.info("STT: '%s'", text)

                        if text.lower() in _END_PHRASES or any(
                            p in text.lower() for p in _END_PHRASES
                        ):
                            await self._say("Arrivederci, stammi bene!")
                            return

                        self._busy.set()
                        drainer = asyncio.create_task(_drain())

                        urgency, reply = await self._combined_chat(text, llm_history)
                        if urgency in ("HIGH", "CRITICAL"):
                            logger.critical("Agent: emergency assessed %s", urgency)
                            if self._dispatch_cb:
                                await self._dispatch_cb(f"URGENCY:{urgency}:{text}")
                            await self._say(
                                "Ho capito, chiamo subito aiuto. Come sta adesso?"
                            )
                            asyncio.create_task(self._wait_for_responder())
                            await _echo_drain()
                        else:
                            await self._say(reply)
                            await _echo_drain()

                        self._busy.clear()
                        await drainer
                        resampler = _AudioResampler()
                        break
                    else:
                        partial = json.loads(rec.PartialResult())
                        ptext = partial.get("partial", "").strip()
                        now = time.monotonic()
                        if ptext:
                            if ptext != last_partial:
                                last_partial = ptext
                                speech_timeout = now + 1.5
                        elif speech_timeout > 0.0 and now > speech_timeout:
                            result = json.loads(rec.FinalResult())
                            if "alternatives" in result:
                                best = max(
                                    result["alternatives"],
                                    key=lambda a: a.get("confidence", 0),
                                )
                                text = best.get("text", "").strip()
                            else:
                                text = result.get("text", "").strip()
                            text = _correct_stt(text) if text else text
                            if text and len(text.split()) >= 2:
                                logger.info("STT (force): '%s'", text)
                                if text.lower() in _END_PHRASES or any(
                                    p in text.lower() for p in _END_PHRASES
                                ):
                                    await self._say("Arrivederci, stammi bene!")
                                    return
                                self._busy.set()
                                drainer = asyncio.create_task(_drain())
                                urgency, reply = await self._combined_chat(
                                    text, llm_history
                                )
                                if urgency in ("HIGH", "CRITICAL"):
                                    logger.critical(
                                        "Agent: emergency assessed %s", urgency
                                    )
                                    if self._dispatch_cb:
                                        await self._dispatch_cb(
                                            f"URGENCY:{urgency}:{text}"
                                        )
                                    await self._say(
                                        "Ho capito, chiamo subito aiuto. Come sta adesso?"
                                    )
                                    asyncio.create_task(self._wait_for_responder())
                                    await _echo_drain()
                                else:
                                    await self._say(reply)
                                    await _echo_drain()
                                self._busy.clear()
                                await drainer
                                resampler = _AudioResampler()
                                break
                            speech_timeout = 0.0
            except StopAsyncIteration:
                break
            except Exception as e:
                logger.error("Agent conversation error: %s", e)
                break
        logger.info("Agent: conversation ended")

    async def _assess_urgency(self, text: str) -> str:
        from alexa_custom.llm import OpenAIClient

        cfg = self._config.llm
        if cfg is None:
            return "NONE"
        client = OpenAIClient(cfg.host, cfg.api_key, cfg.request_timeout)
        try:
            result = await asyncio.wait_for(
                client.chat(
                    [
                        {"role": "system", "content": _URGENCY_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    cfg.model,
                ),
                timeout=10.0,
            )
            result = result.strip().upper()
            for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"):
                if level in result:
                    return level
            return "NONE"
        except Exception as e:
            logger.warning("Urgency assessment failed: %s", e)
            return "NONE"

    async def _combined_chat(self, text: str, history: list[dict]) -> tuple[str, str]:
        from alexa_custom.llm import OpenAIClient

        cfg = self._config.llm
        if cfg is None:
            return "NONE", "Scusa, non ho capito."
        if self._llm_client is None:
            self._llm_client = OpenAIClient(cfg.host, cfg.api_key, cfg.request_timeout)
        history.append({"role": "user", "content": text})
        self._conversation_history.append(f"Utente: {text}")
        try:
            result = await asyncio.wait_for(
                self._llm_client.chat(history, cfg.model),
                timeout=cfg.request_timeout,
            )
            result = result.strip()
        except Exception as e:
            logger.error("LLM chat error: %s", e)
            history.pop()
            return "NONE", "Scusa, non ho capito. Puoi ripetere?"

        urgency = "NONE"
        for line in result.split("\n"):
            uline = line.strip().upper()
            for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"):
                if f"URGENZA:{level}" in uline or f"URGENCY:{level}" in uline:
                    urgency = level
                    break
            if urgency != "NONE":
                break

        reply_lines = [
            x
            for x in result.split("\n")
            if "URGENZA:" not in x.upper() and "URGENCY:" not in x.upper()
        ]
        reply = " ".join(x.strip() for x in reply_lines if x.strip())
        if not reply:
            reply = result
        history.append({"role": "assistant", "content": reply})
        self._conversation_history.append(f"Assistente: {reply}")
        return urgency, reply

    async def _llm_chat(self, history: list[dict]) -> str:
        from alexa_custom.llm import OpenAIClient

        cfg = self._config.llm
        if cfg is None:
            return "Scusa, non ho capito."
        host = cfg.host
        client = OpenAIClient(host, cfg.api_key, cfg.request_timeout)
        try:
            result = await asyncio.wait_for(
                client.chat(history, cfg.model),
                timeout=cfg.request_timeout,
            )
            return result.strip()
        except Exception as e:
            logger.error("LLM chat error: %s", e)
            return "Scusa, non ho capito. Puoi ripetere?"


def _resample_numpy(arr: np.ndarray, target_len: int) -> np.ndarray:
    if len(arr) < 2:
        return np.resize(arr, max(target_len, 1))
    try:
        import scipy.signal

        return scipy.signal.resample(arr.astype(np.float32), target_len).astype(
            np.int16
        )
    except ImportError:
        x = np.linspace(0, len(arr) - 1, num=len(arr))
        x_new = np.linspace(0, len(arr) - 1, num=target_len)
        return np.interp(x_new, x, arr.astype(np.float32)).astype(np.int16)


def _frame_to_s16le(frame_or_event) -> bytes | None:
    try:
        af = getattr(frame_or_event, "frame", frame_or_event)
        data = bytes(af.data)
        nc = getattr(af, "num_channels", 1)
        if nc > 1:
            arr = np.frombuffer(data, dtype=np.int16)
            return arr[::nc].tobytes()
        return data
    except Exception as e:
        logger.warning("Frame conversion error: %s", e)
        return None


class _AudioResampler:
    def __init__(self):
        self._buf = bytearray()
        self._method = None

    def feed(self, data: bytes) -> np.ndarray | None:
        self._buf.extend(data)
        frame_size = 48000 // 20  # 50ms chunks
        if len(self._buf) < frame_size * 2:
            return None
        chunk = bytes(self._buf[:frame_size])
        self._buf = self._buf[frame_size:]
        return self._resample(chunk)

    def _resample(self, chunk: bytes) -> np.ndarray:
        arr = np.frombuffer(chunk, dtype=np.int16)
        if self._method is None:
            try:
                import scipy.signal

                self._method = "scipy"
            except ImportError:
                self._method = "decimate"
        if self._method == "scipy":
            import scipy.signal

            target_len = len(arr) * 16000 // 48000
            return scipy.signal.resample(arr.astype(np.float32), target_len).astype(
                np.int16
            )
        return arr[::3]
