from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class SOSNotifier:
    def __init__(
        self,
        twilio_account_sid: str = "",
        twilio_auth_token: str = "",
        twilio_from_number: str = "",
        sos_phone_number: str = "",
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
    ):
        self._twilio_account_sid = twilio_account_sid
        self._twilio_auth_token = twilio_auth_token
        self._twilio_from_number = twilio_from_number
        self._sos_phone_number = sos_phone_number
        self._telegram_bot_token = telegram_bot_token
        self._telegram_chat_id = telegram_chat_id

    async def call_for_help(self, room: str) -> None:
        tasks = []
        if self._twilio_account_sid and self._sos_phone_number:
            tasks.append(self._place_twilio_call(room))
        if self._telegram_bot_token and self._telegram_chat_id:
            tasks.append(self._send_telegram(room))
        if tasks:
            await asyncio.gather(*tasks)

    async def _place_twilio_call(self, room: str) -> None:
        try:
            auth = httpx.BasicAuth(self._twilio_account_sid, self._twilio_auth_token)
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self._twilio_account_sid}/Calls.json"
            data = {
                "To": self._sos_phone_number,
                "From": self._twilio_from_number,
                "Twiml": f"<Response><Say language='it-IT'>Richiesta di emergenza ricevuta. "
                f"La stanza LiveKit è {room}. "
                f"Collegarsi per assistere l'utente.</Say></Response>",
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, auth=auth, data=data)
                if resp.status_code == 201:
                    logger.info("Twilio call placed to %s", self._sos_phone_number)
                else:
                    logger.error("Twilio call failed: %s %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("Twilio call error: %s", e)

    async def _send_telegram(self, room: str) -> None:
        import urllib.parse

        try:
            url = f"https://api.telegram.org/bot{self._telegram_bot_token}/sendMessage"
            livekit_url = __import__("os").environ.get("LIVEKIT_URL", "")
            params = urllib.parse.urlencode({
                "liveKitUrl": livekit_url,
                "token": "",
            })
            join_url = f"https://meet.livekit.io/custom/?{params}"
            text = (
                f"🚨 RICHIESTA DI EMERGENZA SOS\n\n"
                f"Stanza: {room}\n"
                f"Link per unirsi: {join_url}\n"
                f"Timestamp: {__import__('time').time()}"
            )
            payload = {
                "chat_id": self._telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info("Telegram SOS notification sent")
                else:
                    logger.error("Telegram send failed: %s %s", resp.status_code, resp.text)
        except Exception as e:
            logger.error("Telegram error: %s", e)
