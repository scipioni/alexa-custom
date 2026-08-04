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


class TestStateSuppression(unittest.TestCase):
    """`idle` is the daemon's resting state and would dominate the state topic
    (and the QoS-1 bridge queue to the master broker) without saying anything."""

    def test_idle_state_is_not_queued(self):
        client = _client()
        asyncio.run(client.publish(client.state_topic, "idle"))
        assert _queued(client) == []

    def test_other_states_still_publish(self):
        client = _client()

        async def _run():
            for state in ("listening", "speaking", "gated", "offline"):
                await client.publish(client.state_topic, state)

        asyncio.run(_run())
        assert [p for _, p, _ in _queued(client)] == [
            "listening",
            "speaking",
            "gated",
            "offline",
        ]

    def test_idle_on_another_topic_still_publishes(self):
        # Only the state topic is filtered — an action or command payload that
        # happens to be the word "idle" must go through untouched.
        client = _client()
        topic = f"{client.topic_prefix}/{client.node_id}/command"
        asyncio.run(client.publish(topic, "idle"))
        assert _queued(client) == [(topic, "idle", False)]

    def test_threadsafe_publish_is_filtered_too(self):
        # publish_threadsafe() funnels into publish(), so the suppression must
        # hold for the STT worker thread's _publish_state() as well.
        client = _client()

        async def _run():
            client._loop = asyncio.get_running_loop()
            client.publish_threadsafe(client.state_topic, "idle")
            client.publish_threadsafe(client.state_topic, "listening")
            await asyncio.sleep(0)  # let the scheduled publish tasks run
            await asyncio.sleep(0)

        asyncio.run(_run())
        assert [p for _, p, _ in _queued(client)] == ["listening"]
