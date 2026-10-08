"""Per-connection identities and cleanup are prerequisites for shared Agent clients."""
import asyncio
import json
import threading
import pytest
import websockets
from mklink.remote.agent import SiteAgent
from mklink.remote.protocol import PROTOCOL_VERSION
from test_remote_capabilities import _running_agent, _request


async def handshake(socket):
    await socket.send(_request('system.handshake', {'protocol_version': PROTOCOL_VERSION}))
    assert 'result' in json.loads(await socket.recv())


async def echo(socket):
    await socket.send(_request('test.echo'))
    return json.loads(await socket.recv())['result']['client_id']


@pytest.mark.parametrize('callback_form', ['sync', 'async', 'awaitable'])
def test_connections_keep_distinct_ids_and_detach_independently(callback_form):
    async def scenario():
        closed = []
        notified = threading.Event()
        def record(client_id):
            closed.append(client_id)
            notified.set()
        async def async_record(client_id):
            record(client_id)
        callback = record if callback_form == 'sync' else async_record
        if callback_form == 'awaitable':
            callback = lambda client_id: async_record(client_id)
        async with _running_agent(
            request_dispatcher=lambda op, params, context: {'client_id': context.client_id},
            client_closed=callback,
        ) as agent:
            url = f'ws://127.0.0.1:{agent.port}'
            async with websockets.connect(url) as first, websockets.connect(url) as second:
                await handshake(first); await handshake(second)
                first_id, second_id = await echo(first), await echo(second)
                assert first_id and second_id and first_id != second_id
                assert await echo(first) == first_id
                await first.close()
                assert await asyncio.to_thread(notified.wait, 2)
                assert closed == [first_id]
                assert await echo(second) == second_id
        assert sorted(closed) == sorted([first_id, second_id])
    asyncio.run(scenario())


def test_disconnect_cleanup_waits_for_inflight_operation():
    async def scenario():
        entered, release, detached = threading.Event(), threading.Event(), threading.Event()
        order = []
        def dispatch(op, params, context):
            order.append(('start', context.client_id)); entered.set()
            assert release.wait(3)
            order.append(('finish', context.client_id))
            return {}
        def closed(client_id):
            order.append(('close', client_id)); detached.set()
        async with _running_agent(request_dispatcher=dispatch, client_closed=closed) as agent:
            async with websockets.connect(f'ws://127.0.0.1:{agent.port}') as socket:
                await handshake(socket)
                await socket.send(_request('test.blocked'))
                try:
                    assert await asyncio.to_thread(entered.wait, 2)
                    await socket.close()
                    assert not detached.is_set()
                finally:
                    release.set()
                assert await asyncio.to_thread(detached.wait, 2)
        assert [item[0] for item in order] == ['start', 'finish', 'close']
        assert len({item[1] for item in order}) == 1
    asyncio.run(scenario())


def test_cancelled_sync_callback_drains_returned_awaitable_before_finishing():
    async def scenario():
        entered, release = threading.Event(), threading.Event()
        async_entered, async_release = asyncio.Event(), asyncio.Event()
        order = []
        async def finish():
            order.append('async'); async_entered.set()
            await async_release.wait()
            order.append('done')
        def callback():
            order.append('sync'); entered.set()
            assert release.wait(3)
            return finish()
        task = asyncio.create_task(SiteAgent._invoke_lower_level(callback))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel(); release.set()
            await asyncio.wait_for(async_entered.wait(), 2)
            assert not task.done()
            async_release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set(); async_release.set()
        assert order == ['sync', 'async', 'done']
    asyncio.run(scenario())


def test_cancelled_reconnect_finishes_before_connection_cleanup():
    from types import SimpleNamespace
    from mklink.remote.agent import AgentConfig
    async def scenario():
        entered, release, detached = threading.Event(), threading.Event(), threading.Event()
        order = []
        def factory(**kwargs):
            entered.set()
            assert release.wait(3)
            order.append('connected')
            return SimpleNamespace(connected=True, close=lambda: None)
        def closed(client_id):
            order.append('closed'); detached.set()
        messages = iter([_request('system.handshake', {'protocol_version': PROTOCOL_VERSION}),
                         _request('agent.reconnect')])
        class Socket:
            async def recv(self): return next(messages)
            async def send(self, message): pass
        agent = SiteAgent(AgentConfig(), device_factory=factory, client_closed=closed)
        task = asyncio.create_task(agent._handle_connection(Socket()))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            assert not await asyncio.to_thread(detached.wait, .1)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert order == ['connected', 'closed']
        finally:
            release.set()
            await asyncio.to_thread(agent.close)
    asyncio.run(scenario())
