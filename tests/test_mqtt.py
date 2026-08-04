import asyncio
import unittest

from alexa_custom.mqtt import MQTTClient


def _client() -> MQTTClient:
    return MQTTClient(host="127.0.0.1", topic_prefix="serena", node_id="arduino")


def _queued(client: MQTTClient) -> list[tuple[str, str, bool]]:
    out = []
    while not client._queue.empty():
        out.append(client._queue.get_nowait())
    return out


class TestStateDeduplication(unittest.TestCase):
    """Only state *transitions* reach the broker. "idle" is the resting state the
    daemon returns to from several places, so a single reply used to emit it
    twice in a row — and every copy crosses the QoS-1 bridge to the master."""

    def test_repeated_state_published_once(self):
        client = _client()

        async def _run():
            for state in ("speaking", "idle", "idle", "idle"):
                await client.publish(client.state_topic, state)

        asyncio.run(_run())
        assert [p for _, p, _ in _queued(client)] == ["speaking", "idle"]

    def test_transitions_all_published(self):
        client = _client()

        async def _run():
            for state in ("idle", "listening", "speaking", "idle", "listening"):
                await client.publish(client.state_topic, state)

        asyncio.run(_run())
        # Alternating back to a previous value is a transition, not a duplicate.
        assert [p for _, p, _ in _queued(client)] == [
            "idle",
            "listening",
            "speaking",
            "idle",
            "listening",
        ]

    def test_other_topics_are_never_deduplicated(self):
        # Two identical voice commands in a row are two real events.
        client = _client()
        topic = f"{client.topic_prefix}/{client.node_id}/command"

        async def _run():
            await client.publish(topic, "accendi la luce")
            await client.publish(topic, "accendi la luce")

        asyncio.run(_run())
        assert len(_queued(client)) == 2

    def test_reconnect_resends_the_current_state(self):
        # Subscribers may have missed state during the outage, so the baseline is
        # cleared on connect and the next publish goes out even if unchanged.
        client = _client()

        async def _run():
            await client.publish(client.state_topic, "idle")
            _queued(client)
            client._last_state = None  # what run() does on (re)connect
            await client.publish(client.state_topic, "idle")

        asyncio.run(_run())
        assert [p for _, p, _ in _queued(client)] == ["idle"]

    def test_threadsafe_publish_is_deduplicated_too(self):
        # publish_threadsafe() funnels into publish(), so the STT worker thread's
        # _publish_state() is covered by the same filter.
        client = _client()

        async def _run():
            client._loop = asyncio.get_running_loop()
            client.publish_threadsafe(client.state_topic, "idle")
            client.publish_threadsafe(client.state_topic, "idle")
            await asyncio.sleep(0)  # let the scheduled publish tasks run
            await asyncio.sleep(0)

        asyncio.run(_run())
        assert [p for _, p, _ in _queued(client)] == ["idle"]


class TestLocalIdMirroring(unittest.TestCase):
    """node_id and local_id are equivalent addresses for the same board."""

    def test_default_local_id_matches_node_id_no_duplicate(self):
        # _client() uses node_id="arduino", matching the local_id default.
        client = _client()

        async def _run():
            await client.publish(client.state_topic, "listening")

        asyncio.run(_run())
        assert [t for t, _, _ in _queued(client)] == ["serena/arduino/state"]

    def test_distinct_local_id_mirrors_state_publish(self):
        client = MQTTClient(
            host="127.0.0.1", topic_prefix="serena", node_id="galileo"
        )
        assert client.local_id == "arduino"

        async def _run():
            await client.publish(client.state_topic, "listening")

        asyncio.run(_run())
        assert sorted(t for t, _, _ in _queued(client)) == [
            "serena/arduino/state",
            "serena/galileo/state",
        ]

    def test_non_node_topics_are_not_mirrored(self):
        # Discovery config topics don't include node_id in the prefix position
        # expected by _topic_variants(), so they pass through untouched.
        client = MQTTClient(
            host="127.0.0.1", topic_prefix="serena", node_id="galileo"
        )

        async def _run():
            await client.publish("homeassistant/sensor/galileo_status/config", "{}")

        asyncio.run(_run())
        assert [t for t, _, _ in _queued(client)] == [
            "homeassistant/sensor/galileo_status/config"
        ]

    def test_explicit_local_id_equal_to_node_id_is_not_duplicated(self):
        client = MQTTClient(
            host="127.0.0.1",
            topic_prefix="serena",
            node_id="galileo",
            local_id="galileo",
        )

        async def _run():
            await client.publish(client.state_topic, "listening")

        asyncio.run(_run())
        assert [t for t, _, _ in _queued(client)] == ["serena/galileo/state"]
