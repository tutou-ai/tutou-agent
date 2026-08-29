import asyncio
import json

import pytest

from services.live_dashboard.app import LiveEventBroker, create_app
from services.live_dashboard.schema import LiveEvent


def test_broker_emits_snapshot_then_new_events_without_leaking_between_clients():
    async def scenario():
        broker = LiveEventBroker(queue_size=2, heartbeat_seconds=0.05)
        original = LiveEvent(stage="goal", status="running", action="started")
        stream = broker.subscribe([original])

        snapshot = await anext(stream)
        assert snapshot.startswith("event: snapshot\n")
        snapshot_payload = json.loads(snapshot.split("data: ", 1)[1])
        assert snapshot_payload == {"events": [original.model_dump(mode="json")]}

        update = LiveEvent(stage="test", status="passed", action="34 tests passed")
        await broker.publish(update)
        frame = await anext(stream)
        assert frame.startswith("event: event\n")
        assert json.loads(frame.split("data: ", 1)[1]) == update.model_dump(mode="json")

        await stream.aclose()
        assert broker.subscriber_count == 0

    asyncio.run(scenario())


def test_broker_deduplicates_snapshot_events_already_queued_during_connect():
    async def scenario():
        broker = LiveEventBroker(queue_size=2, heartbeat_seconds=0.05)
        snapshot_event = LiveEvent(status="snapshot")
        stream = broker.subscribe([snapshot_event])
        await broker.publish(snapshot_event)
        update = LiveEvent(status="new")
        await broker.publish(update)

        await anext(stream)
        frame = await anext(stream)

        assert json.loads(frame.split("data: ", 1)[1])["id"] == update.id
        await stream.aclose()

    asyncio.run(scenario())


def test_stream_registers_subscriber_before_loading_history(tmp_path):
    app = create_app(database=tmp_path / "events.db", token="test-token")
    broker = LiveEventBroker(heartbeat_seconds=0.05)
    subscriber_counts = []

    class ObservedStore:
        def history(self):
            subscriber_counts.append(broker.subscriber_count)
            return []

    app.state.broker = broker
    app.state.store = ObservedStore()
    stream_endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/live/stream"
    )

    async def scenario():
        response = await stream_endpoint()
        await anext(response.body_iterator)
        await response.body_iterator.aclose()

    asyncio.run(scenario())

    assert subscriber_counts == [1]
    assert broker.subscriber_count == 0


def test_broker_queue_is_bounded_and_keeps_the_newest_event():
    async def scenario():
        broker = LiveEventBroker(queue_size=1, heartbeat_seconds=0.05)
        stream = broker.subscribe([])
        await anext(stream)  # snapshot registers this subscriber
        await broker.publish(LiveEvent(status="old"))
        await broker.publish(LiveEvent(status="new"))
        frame = await anext(stream)
        assert json.loads(frame.split("data: ", 1)[1])["status"] == "new"
        await stream.aclose()

    asyncio.run(scenario())


def test_broker_rejects_subscribers_beyond_its_bound():
    async def scenario():
        broker = LiveEventBroker(max_subscribers=1, heartbeat_seconds=0.05)
        first = broker.subscribe([])

        assert broker.subscriber_count == 1
        with pytest.raises(RuntimeError, match="subscriber limit reached"):
            broker.subscribe([])

        await anext(first)
        await first.aclose()

    asyncio.run(scenario())
