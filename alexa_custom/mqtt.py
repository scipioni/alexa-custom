import asyncio
import json
import logging
import socket
from typing import Any, Awaitable, Callable

import aiomqtt

logger = logging.getLogger(__name__)


class MQTTClient:
    def __init__(
        self,
        host: str,
        port: int = 1883,
        topic_prefix: str = "alexa",
        node_id: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.topic_prefix = topic_prefix
        self.node_id = node_id or socket.gethostname()
        self.client: aiomqtt.Client | None = None
        self._queue: asyncio.Queue[tuple[str, str, bool]] = asyncio.Queue()
        self._on_command_callback: (
            Callable[[dict[str, Any]], Awaitable[None]] | None
        ) = None

    def set_on_command(
        self, callback: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        self._on_command_callback = callback

    async def run(self) -> None:
        """Background loop for MQTT connection and message processing."""
        while True:
            try:
                async with aiomqtt.Client(hostname=self.host, port=self.port) as client:
                    self.client = client
                    logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")

                    # 1. Register with Home Assistant
                    await self._publish_discovery()

                    # 2. Subscribe to command topics
                    await client.subscribe(
                        f"{self.topic_prefix}/{self.node_id}/tts/set"
                    )
                    await client.subscribe(
                        f"{self.topic_prefix}/{self.node_id}/action/run"
                    )

                    # 3. Start publisher and subscriber tasks
                    await asyncio.gather(
                        self._publisher_loop(),
                        self._subscriber_loop(),
                    )
            except aiomqtt.MqttError as e:
                logger.error(f"MQTT connection error: {e}. Retrying in 5 seconds...")
                self.client = None
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected MQTT error: {e}")
                self.client = None
                await asyncio.sleep(5)

    async def _publish_discovery(self) -> None:
        """Publish HA Discovery payloads."""
        device = {
            "identifiers": [f"alexa_custom_{self.node_id}"],
            "name": f"Alexa Assistant ({self.node_id})",
            "model": "Alexa Custom",
            "manufacturer": "Custom",
        }

        # 1. State Sensor (idle, listening, etc)
        state_config = {
            "name": "Status",
            "state_topic": f"{self.topic_prefix}/{self.node_id}/state",
            "unique_id": f"alexa_{self.node_id}_status",
            "device": device,
        }
        await self.publish(
            f"homeassistant/sensor/{self.node_id}_status/config",
            json.dumps(state_config),
            retain=True,
        )

        # 2. TTS Text Input
        tts_config = {
            "name": "Speak Text",
            "command_topic": f"{self.topic_prefix}/{self.node_id}/tts/set",
            "unique_id": f"alexa_{self.node_id}_tts",
            "device": device,
        }
        await self.publish(
            f"homeassistant/text/{self.node_id}_tts/config",
            json.dumps(tts_config),
            retain=True,
        )

        # 3. Command Event (forwarded voice commands)
        # Note: 'event' is a newer HA component, using a generic sensor for backward compatibility
        cmd_config = {
            "name": "Last Command",
            "state_topic": f"{self.topic_prefix}/{self.node_id}/command",
            "value_template": "{{ value_json.text }}",
            "unique_id": f"alexa_{self.node_id}_command",
            "device": device,
        }
        await self.publish(
            f"homeassistant/sensor/{self.node_id}_command/config",
            json.dumps(cmd_config),
            retain=True,
        )

        logger.info("Published Home Assistant Discovery payloads")

    async def _publisher_loop(self) -> None:
        """Drain the outgoing queue and publish messages."""
        while True:
            topic, payload, retain = await self._queue.get()
            if self.client:
                try:
                    await self.client.publish(topic, payload, retain=retain)
                except Exception as e:
                    logger.error(f"Failed to publish to {topic}: {e}")
            self._queue.task_done()

    async def _subscriber_loop(self) -> None:
        """Listen for incoming MQTT messages."""
        if not self.client:
            return
        async with self.client.messages() as messages:
            async for message in messages:
                topic = str(message.topic)
                payload = (
                    message.payload.decode()
                    if isinstance(message.payload, bytes)
                    else str(message.payload)
                )

                logger.debug(f"Received MQTT message on {topic}: {payload}")

                if self._on_command_callback:
                    if topic.endswith("/tts/set"):
                        await self._on_command_callback(
                            {"type": "say", "params": {"text": payload}}
                        )
                    elif topic.endswith("/action/run"):
                        try:
                            action_data = json.loads(payload)
                            await self._on_command_callback(action_data)
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON action payload: {payload}")

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        """Queue a message for publication."""
        await self._queue.put((topic, payload, retain))

    def publish_threadsafe(
        self,
        topic: str,
        payload: str,
        retain: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Thread-safe way to queue a message for publication."""
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.error("No running event loop found for threadsafe publish")
                return

        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self.publish(topic, payload, retain))
        )
