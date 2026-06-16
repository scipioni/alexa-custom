from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import aiomqtt

logger = logging.getLogger(__name__)


class SOSMQTTListener:
    def __init__(
        self,
        host: str,
        port: int,
        topic: str,
        on_sos_request: Callable[[str], Awaitable[None]],
    ):
        self._host = host
        self._port = port
        self._topic = topic
        self._on_sos_request = on_sos_request
        self._stop = asyncio.Event()

    async def run(self):
        logger.info("SOS MQTT listener connecting to %s:%s", self._host, self._port)
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(self._host, self._port) as client:
                    await client.subscribe(self._topic)
                    logger.info("Subscribed to %s — waiting for SOS requests", self._topic)
                    async for message in client.messages:
                        if self._stop.is_set():
                            break
                        try:
                            payload = json.loads(message.payload.decode())
                            room = payload.get("room", "")
                            if room:
                                logger.info("SOS request received for room: %s", room)
                                await self._on_sos_request(room)
                            else:
                                logger.warning("SOS payload missing 'room' field: %s", payload)
                        except json.JSONDecodeError:
                            logger.warning("Invalid SOS payload: %s", message.payload)
            except Exception as e:
                logger.error("MQTT error: %s — reconnecting in 5s", e)
                await asyncio.sleep(5)

    def stop(self):
        self._stop.set()
