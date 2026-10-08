"""Thread ingress is bounded before callbacks reach asyncio client queues."""
import asyncio
import threading

import pytest

from mklink.remote.dashboards import AsyncBridge
from mklink.remote.stream_hub import StreamHub


def test_sse_producer_only_mutates_queues_on_the_owner_loop():
    async def scenario():
        bridge = AsyncBridge()
        queue = bridge.add_client()
        owner = threading.get_ident()
        mutations = []
        original = queue.put_nowait
        def record(value):
            mutations.append(threading.get_ident())
            original(value)
        queue.put_nowait = record
        thread = threading.Thread(target=bridge.put, args=({'event': 'sample'},))
        thread.start()
        thread.join(1)
        assert not thread.is_alive()
        await asyncio.sleep(0)
        assert mutations == [owner]
        assert await asyncio.wait_for(queue.get(), .5) == {'event': 'sample'}
        bridge.remove_client(queue)
    asyncio.run(scenario())


def test_sse_stop_survives_a_full_queue_and_late_data():
    async def scenario():
        bridge = AsyncBridge(maxsize=1)
        queue = bridge.add_client()
        bridge.put('full')
        await asyncio.sleep(0)
        bridge.stop()
        bridge.put('too late')
        await asyncio.sleep(0)
        assert queue.get_nowait() is None
        assert queue.empty()
        bridge.remove_client(queue)
        new = bridge.add_client()
        bridge.put('restarted')
        await asyncio.sleep(0)
        assert new.get_nowait() == 'restarted'
        bridge.remove_client(new)
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['sse', 'binary'])
def test_producer_burst_schedules_one_bounded_delivery(monkeypatch, kind):
    async def scenario():
        hub = StreamHub(2) if kind == 'binary' else AsyncBridge(2)
        queue = hub.subscribe() if kind == 'binary' else hub.add_client()
        pending = []
        loop = asyncio.get_running_loop()
        with monkeypatch.context() as patch:
            patch.setattr(loop, 'call_soon_threadsafe', lambda callback, *args, **kwargs: pending.append((callback, args)))
            for value in range(10000):
                if kind == 'binary':
                    hub.publish(str(value).encode(), 1)
                else:
                    hub.put(value)
            assert len(pending) == 1
            if kind == 'binary':
                assert sum(hub._pending_by_generation.values()) <= 2
        for callback, args in pending:
            callback(*args)
        expected = [b'9998', b'9999'] if kind == 'binary' else [9998, 9999]
        assert [queue.get_nowait(), queue.get_nowait()] == expected
        if kind == 'binary':
            assert hub.stats().dropped_batches == 9998
            assert hub.stats().delivered_batches == 2
            hub.unsubscribe(queue)
        else:
            hub.remove_client(queue)
    asyncio.run(scenario())


def test_pending_binary_metadata_survives_ingress_overflow(monkeypatch):
    async def scenario():
        hub = StreamHub(2)
        hub.set_subscribe_callback(lambda enqueue: enqueue(b'metadata', 0))
        loop = asyncio.get_running_loop()
        callbacks = []
        with monkeypatch.context() as patch:
            patch.setattr(loop, 'call_soon_threadsafe', lambda callback, *args: callbacks.append((callback, args)))
            queue = hub.subscribe()
            for _ in range(10000):
                hub.publish(b'data', 1)
            assert len(callbacks) == 1
            assert sum(hub._pending_by_generation.values()) <= 2
        for callback, args in callbacks:
            callback(*args)
        assert queue.get_nowait() == b'metadata'
        assert queue.get_nowait() == b'data'
        hub.unsubscribe(queue)
    asyncio.run(scenario())


def test_sse_stop_preserves_prior_data_when_there_is_capacity():
    async def scenario():
        bridge = AsyncBridge(4)
        queue = bridge.add_client()
        bridge.put('one')
        bridge.put('two')
        bridge.stop()
        bridge.put('late')
        await asyncio.sleep(0)
        assert [queue.get_nowait() for _ in range(3)] == ['one', 'two', None]
        assert queue.empty()
        bridge.remove_client(queue)
    asyncio.run(scenario())


def test_sse_stop_survives_ingress_overflow_and_new_subscribers():
    async def scenario():
        bridge = AsyncBridge(1)
        first = bridge.add_client()
        bridge.stop()
        second = bridge.add_client()
        for value in range(100):
            bridge.put(value)
        bridge.stop()
        await asyncio.sleep(0)
        assert first.get_nowait() is None
        assert second.get_nowait() is None
        bridge.remove_client(first)
        bridge.remove_client(second)
        assert not bridge._closing_clients and not bridge._ended_clients
    asyncio.run(scenario())


def test_every_binary_subscriber_receives_metadata_during_ingress_pressure():
    async def scenario():
        hub = StreamHub(1)
        hub.set_subscribe_callback(lambda enqueue: enqueue(b'metadata', 0))
        clients = []
        for _ in range(100):
            clients.append(hub.subscribe())
            hub.publish(b'sample', 1)
        await asyncio.sleep(0)
        for queue in clients:
            assert queue.get_nowait() == b'metadata'
            hub.unsubscribe(queue)
        assert hub.stats().active_clients == 0
        assert not hub._pending_by_generation
    asyncio.run(scenario())


def test_binary_initial_snapshot_does_not_overtake_previous_batches():
    async def scenario():
        hub = StreamHub(4)
        hub.set_subscribe_callback(lambda enqueue: enqueue(b'metadata', 0))
        first = hub.subscribe()
        assert first.get_nowait().sequence == 1
        hub.publish(b'sample', 1)
        second = hub.subscribe()
        assert [first.get_nowait().sequence for _ in range(2)] == [2, 3]
        assert second.get_nowait().sequence == 3
        await asyncio.sleep(0)
        hub.unsubscribe(first)
        hub.unsubscribe(second)
    asyncio.run(scenario())


def test_binary_closed_loop_discards_all_pending_accounting(monkeypatch):
    loop = asyncio.new_event_loop()
    hub = StreamHub(2)
    async def prepare():
        hub.subscribe()
        # Keep the callback pending while closing the loop, as in abrupt exit.
        monkeypatch.setattr(loop, 'call_soon_threadsafe', lambda *args: None)
        hub.publish(b'pending', 1)
    try:
        loop.run_until_complete(prepare())
    finally:
        loop.close()
    with pytest.raises(RuntimeError, match='loop is closed'):
        hub.publish(b'late', 1)
    assert not hub._pending_by_generation
    assert hub.stats().dropped_batches == 2


def test_sse_loop_cannot_be_stolen_by_a_second_thread():
    errors = []
    async def scenario():
        bridge = AsyncBridge()
        queue = bridge.add_client()
        async def stealing():
            try:
                bridge.add_client()
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=lambda: asyncio.run(stealing()))
        thread.start()
        thread.join(1)
        assert not thread.is_alive()
        assert errors == ['SSE clients must use the owner event loop']
        bridge.remove_client(queue)
    asyncio.run(scenario())
