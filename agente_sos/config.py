from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SOSConfig:
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_topic: str = "sos/request"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    agent_identity: str = "agente-sos"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    sos_phone_number: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    llm_model: str = "llama-3.1-8b-instant"
    llm_base_url: str = "https://api.groq.com/openai"
    llm_timeout: float = 30.0
    vosk_model_path: str = "models/it"
    tts_voice_path: str = "models/piper/it_IT-paola-medium.onnx"

    @classmethod
    def from_env(cls) -> SOSConfig:
        return cls(
            mqtt_host=os.environ.get("MQTT_HOST", ""),
            mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
            mqtt_topic=os.environ.get("SOS_MQTT_TOPIC", "sos/request"),
            livekit_url=os.environ.get("LIVEKIT_URL", ""),
            livekit_api_key=os.environ.get("LIVEKIT_API_KEY", ""),
            livekit_api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
            twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
            twilio_from_number=os.environ.get("TWILIO_FROM_NUMBER", ""),
            sos_phone_number=os.environ.get("SOS_PHONE_NUMBER", ""),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            llm_model=os.environ.get("SOS_LLM_MODEL", "llama-3.1-8b-instant"),
            llm_base_url=os.environ.get("SOS_LLM_BASE_URL", "https://api.groq.com/openai"),
            llm_timeout=float(os.environ.get("SOS_LLM_TIMEOUT", "30")),
            vosk_model_path=os.environ.get("SOS_VOSK_MODEL_PATH", "models/it"),
            tts_voice_path=os.environ.get("SOS_TTS_VOICE_PATH", "models/piper/it_IT-paola-medium.onnx"),
        )
