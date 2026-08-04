import asyncio
import json
import logging
import socket
from typing import Any, Awaitable, Callable

import aiomqtt

from alexa_custom import metrics

logger = logging.getLogger(__name__)


class MQTTClient:
    def __init__(
        self,
        host: str,
        port: int = 1883,
        topic_prefix: str = "alexa",
        node_id: str | None = None,
        local_id: str = "arduino",
        queue_max: int = 200,
    ) -> None:
        self.host = host
        self.port = port
        self.topic_prefix = topic_prefix
        self.node_id = node_id or socket.gethostname()
        # Fixed local alias, independent of the (possibly per-board-unique)
        # node_id — lets a bridge/automation template hardcoded to
        # "<topic_prefix>/arduino/..." keep working across boards without
        # per-board edits. Every command topic and outgoing publish under
        # node_id is mirrored under local_id (see _topic_variants()).
        self.local_id = local_id
        self.client: aiomqtt.Client | None = None
        self._queue: asyncio.Queue[tuple[str, str, bool]] = asyncio.Queue(
            maxsize=queue_max
        )
        self._queue_max = queue_max
        self._on_command_callback: (
            Callable[[dict[str, Any]], Awaitable[None]] | None
        ) = None
        self._run_task: asyncio.Task | None = None
        self._stopping = False
        self._loop: asyncio.AbstractEventLoop | None = None
        # Last value published on the state topic, for consecutive-duplicate
        # suppression. Cleared on every (re)connect so the first state after a
        # reconnect is always sent, even if it repeats the pre-outage value.
        self._last_state: str | None = None

    def set_on_command(
        self, callback: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        self._on_command_callback = callback

    async def run(self) -> None:
        """Background loop for MQTT connection and message processing."""
        self._run_task = asyncio.current_task()
        self._loop = asyncio.get_running_loop()
        while not self._stopping:
            try:
                async with aiomqtt.Client(hostname=self.host, port=self.port) as client:
                    self.client = client
                    logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")
                    # Forget the deduplication baseline: subscribers may have
                    # missed state while we were disconnected, so the next
                    # publish must go out even if it repeats the last value.
                    self._last_state = None

                    # 1. Register with Home Assistant
                    await self._publish_discovery()

                    # 2. Subscribe to command topics, under both the node_id
                    # and the fixed local_id alias (deduped when they match).
                    for node in self._ids:
                        await client.subscribe(f"{self.topic_prefix}/{node}/tts/set")
                        await client.subscribe(
                            f"{self.topic_prefix}/{node}/action/run"
                        )
                        await client.subscribe(
                            f"{self.topic_prefix}/{node}/trigger/run"
                        )

                    # 3. Start publisher and subscriber tasks.
                    # Track both so that when one fails (e.g. subscriber raises
                    # MqttError on disconnect) the sibling is cancelled — otherwise
                    # each reconnect orphans another publisher draining the same
                    # queue, causing duplicate publishes and unbounded task growth.
                    pub = asyncio.create_task(self._publisher_loop())
                    sub = asyncio.create_task(self._subscriber_loop())
                    try:
                        await asyncio.gather(pub, sub)
                    finally:
                        for t in (pub, sub):
                            t.cancel()
                        await asyncio.gather(pub, sub, return_exceptions=True)
            except aiomqtt.MqttError as e:
                logger.error(f"MQTT connection error: {e}. Retrying in 5 seconds...")
                self.client = None
                metrics.inc("mqtt_reconnects")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected MQTT error: {e}")
                self.client = None
                metrics.inc("mqtt_reconnects")
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
        async for message in self.client.messages:
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
                elif topic.endswith("/trigger/run"):
                    await self._on_command_callback({"command": payload})

    @property
    def state_topic(self) -> str:
        return f"{self.topic_prefix}/{self.node_id}/state"

    @property
    def _ids(self) -> list[str]:
        """node_id and local_id, deduplicated, in that order."""
        if self.local_id == self.node_id:
            return [self.node_id]
        return [self.node_id, self.local_id]

    def _topic_variants(self, topic: str) -> list[str]:
        """Mirror a `<topic_prefix>/<node_id>/...` topic onto local_id too.

        node_id and local_id are equivalent addresses for the same board — a
        board-unique node_id keeps HA entities/bridge namespaces distinct per
        board, while the fixed local_id alias (default "arduino") lets a
        bridge/automation template hardcoded to that name work unmodified
        across boards. Topics that don't match the node_id prefix (e.g.
        Home Assistant discovery config topics) are left untouched.
        """
        prefix = f"{self.topic_prefix}/{self.node_id}/"
        if self.local_id == self.node_id or not topic.startswith(prefix):
            return [topic]
        suffix = topic[len(prefix) :]
        return [topic, f"{self.topic_prefix}/{self.local_id}/{suffix}"]

    def _enqueue(self, topic: str, payload: str, retain: bool) -> None:
        try:
            self._queue.put_nowait((topic, payload, retain))
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            logger.warning(
                "MQTT outgoing queue full (%d); dropped oldest message", self._queue_max
            )
            self._queue.put_nowait((topic, payload, retain))

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        """Queue a message for publication, dropping the oldest on overflow.

        Consecutive duplicates on the state topic are dropped: "idle" is the
        resting state the daemon returns to after every wake, dispatch, reply and
        gate release, so a single spoken reply used to emit it twice in a row, and
        every copy is forwarded over the QoS-1 bridge to the master broker. Only
        transitions are published; the state itself is unchanged.

        Deduplicated here rather than at each call site because state is
        published from ~10 places across stt.py and actions.py, and this is the
        one path all of them — including publish_threadsafe() — funnel through.

        The message is mirrored onto the local_id-aliased topic (see
        _topic_variants()) so node_id and local_id stay equivalent.
        """
        if topic == self.state_topic:
            if payload == self._last_state:
                metrics.inc("mqtt_state_deduped")
                return
            self._last_state = payload

        for t in self._topic_variants(topic):
            self._enqueue(t, payload, retain)

    async def publish_offline(self) -> None:
        """Publish offline state and disconnect cleanly (called on graceful shutdown)."""
        if self.client:
            try:
                for t in self._topic_variants(self.state_topic):
                    await asyncio.wait_for(
                        self.client.publish(t, "offline", retain=False),
                        timeout=0.5,
                    )
            except Exception as e:
                logger.debug("publish_offline: %s", e)
        else:
            logger.debug("publish_offline: no active client")

    async def stop(self) -> None:
        """Publish offline state and stop the background run loop (used on
        graceful shutdown and when MQTT settings change on config reload)."""
        self._stopping = True
        try:
            await self.publish_offline()
        except Exception as e:
            logger.debug("stop: publish_offline failed: %s", e)
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    def publish_threadsafe(
        self,
        topic: str,
        payload: str,
        retain: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Thread-safe way to queue a message for publication."""
        if loop is None:
            # Most callers run on a worker thread with no loop of its own, so
            # asyncio.get_running_loop() only ever succeeds for a caller that
            # happens to run on the MQTT client's own loop already — the
            # common case is the opposite. Fall back to the loop run()
            # actually executes on (captured when it started) before giving
            # up, so callers don't all need to thread a loop reference
            # through every layer just to reach this.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = self._loop
            if loop is None:
                logger.error("No running event loop found for threadsafe publish")
                return

        loop.call_soon_threadsafe(
            lambda t=topic, p=payload, r=retain: asyncio.create_task(
                self.publish(t, p, r)
            )
        )
