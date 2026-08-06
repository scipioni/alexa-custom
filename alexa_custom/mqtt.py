import asyncio
import json
import logging
import socket
import time
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
        heartbeat_interval_s: float = 3600.0,
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
        # Interval for the periodic {"state": "alive"} liveness ping (see
        # _heartbeat_loop()). <= 0 disables it.
        self.heartbeat_interval_s = heartbeat_interval_s
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
                        await client.subscribe(f"{self.topic_prefix}/{node}/action/run")
                        await client.subscribe(
                            f"{self.topic_prefix}/{node}/trigger/run"
                        )

                    # 3. Start publisher, subscriber and heartbeat tasks.
                    # Track all three so that when one fails (e.g. subscriber raises
                    # MqttError on disconnect) the others are cancelled — otherwise
                    # each reconnect orphans another publisher draining the same
                    # queue, causing duplicate publishes and unbounded task growth.
                    pub = asyncio.create_task(self._publisher_loop())
                    sub = asyncio.create_task(self._subscriber_loop())
                    hb = asyncio.create_task(self._heartbeat_loop())
                    tasks = (pub, sub, hb)
                    try:
                        await asyncio.gather(*tasks)
                    finally:
                        for t in tasks:
                            t.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
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

        # 1. State Sensor (idle, listening, etc) — payload is JSON
        # ({"state": ..., "timestamp": ...}), so HA needs a value_template to
        # pull out the sensor's actual state.
        state_config = {
            "name": "Status",
            "state_topic": f"{self.topic_prefix}/{self.node_id}/state",
            "value_template": "{{ value_json.state }}",
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

    async def _heartbeat_loop(self) -> None:
        """Publish {"state": "alive"} on a fixed interval as a liveness ping.

        This is not an operational state transition, so it bypasses the
        dedup in publish_state() (via force=True) — otherwise a board that
        sits idle for hours would have its second and later heartbeats
        silently dropped for repeating the previous payload, defeating the
        whole point of a periodic "I'm still here" signal.
        """
        if self.heartbeat_interval_s <= 0:
            return
        while True:
            await asyncio.sleep(self.heartbeat_interval_s)
            await self.publish_state("alive", force=True)

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

        The message is mirrored onto the local_id-aliased topic (see
        _topic_variants()) so node_id and local_id stay equivalent.
        """
        for t in self._topic_variants(topic):
            self._enqueue(t, payload, retain)

    def _state_payload(self, state: str) -> str:
        return json.dumps({"state": state, "timestamp": time.time()})

    async def publish_state(
        self, state: str, retain: bool = False, force: bool = False
    ) -> None:
        """Publish a JSON state update: {"state": ..., "timestamp": ...}.

        Consecutive duplicate states are dropped: "idle" is the resting state
        the daemon returns to after every wake, dispatch, reply and gate
        release, so a single spoken reply used to emit it twice in a row, and
        every copy is forwarded over the QoS-1 bridge to the master broker.
        Only transitions are published; the state itself is unchanged.

        Dedup compares `state`, not the serialized payload — every payload
        embeds a fresh timestamp, so comparing full JSON strings would never
        dedupe anything.

        `force=True` (used by _heartbeat_loop() for the periodic "alive"
        ping) bypasses the dedup check — a liveness signal must go out on
        every tick even if the operational state hasn't changed since the
        last one, otherwise a board idle for hours would have every
        heartbeat after the first silently dropped for "repeating" it.

        Called from ~10 places across stt.py and actions.py; this is the one
        path all of them — including publish_state_threadsafe() — funnel
        through.
        """
        if not force and state == self._last_state:
            metrics.inc("mqtt_state_deduped")
            return
        self._last_state = state
        await self.publish(self.state_topic, self._state_payload(state), retain=retain)

    async def publish_offline(self) -> None:
        """Publish offline state and disconnect cleanly (called on graceful shutdown)."""
        if self.client:
            try:
                payload = self._state_payload("offline")
                for t in self._topic_variants(self.state_topic):
                    await asyncio.wait_for(
                        self.client.publish(t, payload, retain=False),
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

    def _resolve_loop(
        self, loop: asyncio.AbstractEventLoop | None
    ) -> asyncio.AbstractEventLoop | None:
        if loop is not None:
            return loop
        # Most callers run on a worker thread with no loop of its own, so
        # asyncio.get_running_loop() only ever succeeds for a caller that
        # happens to run on the MQTT client's own loop already — the common
        # case is the opposite. Fall back to the loop run() actually executes
        # on (captured when it started) before giving up, so callers don't
        # all need to thread a loop reference through every layer just to
        # reach this.
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return self._loop

    def publish_threadsafe(
        self,
        topic: str,
        payload: str,
        retain: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Thread-safe way to queue a message for publication."""
        loop = self._resolve_loop(loop)
        if loop is None:
            logger.error("No running event loop found for threadsafe publish")
            return

        loop.call_soon_threadsafe(
            lambda t=topic, p=payload, r=retain: asyncio.create_task(
                self.publish(t, p, r)
            )
        )

    def publish_state_threadsafe(
        self,
        state: str,
        retain: bool = False,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Thread-safe equivalent of publish_state(), for callers off the MQTT loop."""
        loop = self._resolve_loop(loop)
        if loop is None:
            logger.error("No running event loop found for threadsafe publish")
            return

        loop.call_soon_threadsafe(
            lambda s=state, r=retain: asyncio.create_task(self.publish_state(s, r))
        )
