from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import web

from agente_sos.agent import SOSAgent
from agente_sos.config import SOSConfig
from agente_sos.mqtt_listener import SOSMQTTListener
from agente_sos.notifier import SOSNotifier

logger = logging.getLogger(__name__)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = SOSConfig.from_env()
    notifier = SOSNotifier(
        twilio_account_sid=config.twilio_account_sid,
        twilio_auth_token=config.twilio_auth_token,
        twilio_from_number=config.twilio_from_number,
        sos_phone_number=config.sos_phone_number,
        telegram_bot_token=config.telegram_bot_token,
        telegram_chat_id=config.telegram_chat_id,
    )

    agent = SOSAgent(config, notifier)
    await agent.start()

    async def on_sos_request(room: str):
        logger.info("SOS request received for room: %s", room)
        asyncio.create_task(agent.handle_room(room))

    # HTTP webhook endpoint for Arduino to POST to
    app = web.Application()

    async def handle_sos(request):
        try:
            body = await request.json()
            room = body.get("room", "")
            if room:
                await on_sos_request(room)
                return web.json_response({"status": "accepted"})
            else:
                return web.json_response({"status": "error", "message": "missing room"}, status=400)
        except Exception as e:
            logger.error("Webhook error: %s", e)
            return web.json_response({"status": "error", "message": str(e)}, status=400)

    app.router.add_post("/sos", handle_sos)
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))

    port = int(__import__("os").environ.get("SOS_HTTP_PORT", "8081"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Agente SOS HTTP endpoint listening on 0.0.0.0:%d/sos", port)

    # Also listen on MQTT if configured
    if config.mqtt_host:
        listener = SOSMQTTListener(
            host=config.mqtt_host,
            port=config.mqtt_port,
            topic=config.mqtt_topic,
            on_sos_request=on_sos_request,
        )
        asyncio.create_task(listener.run())

    logger.info("Agente SOS ready — waiting for SOS requests")
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
