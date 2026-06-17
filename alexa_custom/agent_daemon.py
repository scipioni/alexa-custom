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

from livekit.rtc import AudioStream, Room, TrackKind

logger = logging.getLogger(__name__)

_TRIAGE_PROMPT = (
    "Sei Elsa, assistente sanitaria amichevole. Parla in italiano, "
    "massimo 10 parole per risposta. "
    "Chiedi sintomi brevemente. Se gravi (dolore toracico, "
    "dispnea, incoscienza, emorragia) attiva soccorsi. "
    "Sii rassicurante ma brevissima.\n\n"
    "Prima di rispondere, valuta l'urgenza medica del messaggio "
    "e inizia la risposta con URGENZA:[NONE|LOW|MEDIUM|HIGH|CRITICAL] "
    "poi vai a capo e scrivi la risposta."
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
        self._busy = asyncio.Event()
        self._stop = asyncio.Event()
        self._participant_identity: str | None = None
        self._device_identity: str | None = None
        self._responder_joined = asyncio.Event()
        self._llm_client = None

    def _load_skill(self) -> str:
        skill_path = Path("conf/skills/soccorso-anziani.yaml")
        if not skill_path.is_file():
            return ""
        try:
            import yaml as _yaml

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
        """Send TTS text to the device via LiveKit data channel."""
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

    async def _wait_for_responder(self) -> None:
        """Wait for a responder to join. Resend Telegram link every 30s."""
        for attempt in range(5):
            self._responder_joined.clear()
            try:
                await asyncio.wait_for(self._responder_joined.wait(), timeout=30.0)
                summary = (
                    self._conversation_history[-3:]
                    if self._conversation_history
                    else []
                )
                brief = ". ".join(s.split(": ", 1)[-1] for s in summary)
                if self._device_identity:
                    await self._room.local_participant.publish_data(
                        f"La persona ha bisogno di aiuto. Riassunto: {brief}"
                        if brief
                        else "La persona ha bisogno di aiuto.",
                        reliable=True,
                        topic="tts",
                        destination_identities=[self._device_identity],
                    )
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
        from vosk import KaldiRecognizer

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
            await asyncio.sleep(2.0)

        while self._participant_identity is not None:
            rec = KaldiRecognizer(self._vosk_model, 16000)
            rec.SetWords(True)
            rec.SetPartialWords(True)
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
                        text = result.get("text", "").strip()
                        if not text or len(text.split()) < 2:
                            speech_timeout = 0.0
                            continue
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
                            text = result.get("text", "").strip()
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
