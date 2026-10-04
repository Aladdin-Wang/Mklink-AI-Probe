"""Native presence belongs to the proxy, not the WebView unload request."""
import asyncio

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from mklink.runtime_proxy import create_proxy


def upstream_views():
    upstream = FastAPI()
    views = {8765: {'browser-peer'}, 8775: {'other-probe-peer'}}

    @upstream.post('/api/runtime/control/view')
    async def view(request: Request):
        body = await request.json()
        entries = views[request.url.port]
        if body.get('release'):
            entries.discard(body['client_id'])
        else:
            entries.add(body['client_id'])
        return {'registered': body['client_id'] in entries, 'device_closed': False}

    @upstream.post('/api/runtime/select')
    async def select():
        return {'runtime_url': 'http://127.0.0.1:8775', 'probe_id': 'second'}

    return httpx.ASGITransport(app=upstream), views


def test_native_close_releases_only_its_view_before_shutdown_callback():
    transport, views = upstream_views()
    first = create_proxy({'port': 8765, 'token': 'one'}, port=8766, instance_id='one', transport=transport)
    second = create_proxy({'port': 8765, 'token': 'one'}, port=8767, instance_id='two', transport=transport)
    snapshots = []
    first.state.shutdown = lambda: snapshots.append(set(views[8765]))
    with TestClient(first, base_url='http://127.0.0.1:8766') as a, TestClient(second, base_url='http://127.0.0.1:8767') as b:
        for client in (a, b):
            assert client.post('/api/runtime/control/view', json={'client_id': 'same-page-id'}).status_code == 200
        assert len(views[8765]) == 3
        a.post('/api/runtime/control/view', json={'client_id': 'new-page'})
        a.post('/api/runtime/control/view', json={'client_id': 'same-page-id', 'release': True})
        assert len(views[8765]) == 3  # Reload and late pagehide neither duplicate nor release.
        assert a.post('/api/desktop/shutdown', json={'instance_id': 'wrong'}).status_code == 403
        assert len(views[8765]) == 3
        assert a.post('/api/desktop/shutdown', json={'instance_id': 'one'}).status_code == 200
        assert len(snapshots[0]) == 2 and 'browser-peer' in snapshots[0]
        assert a.post('/api/runtime/control/view', json={'client_id': 'late-heartbeat'}).status_code == 409
        assert len(views[8765]) == 2
        assert views[8775] == {'other-probe-peer'}
    assert views[8765] == {'browser-peer'}  # Lifespan cleanup also releases second.


def test_probe_switch_releases_old_record_and_registers_only_new_backend(monkeypatch):
    from mklink import runtime
    transport, views = upstream_views()
    monkeypatch.setattr(runtime, 'discover', lambda _: {'port': 8775, 'token': 'two', 'probe_id': 'second'})
    app = create_proxy({'port': 8765, 'token': 'one'}, port=8766, instance_id='one', transport=transport)
    with TestClient(app, base_url='http://127.0.0.1:8766') as client:
        client.post('/api/runtime/control/view', json={'client_id': 'page'})
        assert len(views[8765]) == 2
        assert client.post('/api/runtime/select', json={'probe_id': 'second'}).json()['reload']
        assert views[8765] == {'browser-peer'}
        client.post('/api/runtime/control/view', json={'client_id': 'new-page'})
        client.post('/api/runtime/control/view', json={'client_id': 'page', 'release': True})
        assert len(views[8775]) == 2
    assert views[8775] == {'other-probe-peer'}


def test_shutdown_waits_for_inflight_heartbeat_then_removes_record():
    async def scenario():
        entered, complete = asyncio.Event(), asyncio.Event()
        views = set()

        async def handle(request):
            import json
            body = json.loads(request.content)
            if body.get('release'):
                views.discard(body['client_id'])
            else:
                entered.set()
                await complete.wait()
                views.add(body['client_id'])
            return httpx.Response(200, json={'registered': bool(views)})

        app = create_proxy({'port': 8765, 'token': 'one'}, port=8766, instance_id='one', transport=httpx.MockTransport(handle))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8766') as client:
                heartbeat = asyncio.create_task(client.post('/api/runtime/control/view', json={'client_id': 'page'}))
                await entered.wait()
                shutdown = asyncio.create_task(client.post('/api/desktop/shutdown', json={'instance_id': 'one'}))
                await asyncio.sleep(0.01)
                complete.set()
                assert (await heartbeat).status_code == 200
                assert (await shutdown).status_code == 200
                assert not views
    asyncio.run(scenario())


def test_unavailable_backend_does_not_prevent_desktop_exit(caplog):
    def unavailable(request):
        raise httpx.ReadTimeout('unavailable', request=request)
    app = create_proxy({'port': 8765, 'token': 'one'}, port=8766, instance_id='one', transport=httpx.MockTransport(unavailable))
    stopped = []
    app.state.shutdown = lambda: stopped.append(True)
    with TestClient(app, base_url='http://127.0.0.1:8766') as client:
        assert client.post('/api/runtime/control/view', json={'client_id': 'page'}).status_code == 503
        assert client.post('/api/desktop/shutdown', json={'instance_id': 'one'}).status_code == 200
    assert stopped == [True]
    assert 'runtime TTL will expire' in caplog.text


def test_lost_registration_response_is_still_released_on_close():
    import json
    views = set()

    def handle(request):
        body = json.loads(request.content)
        if body.get('release'):
            views.discard(body['client_id'])
            return httpx.Response(200, json={'registered': False})
        views.add(body['client_id'])
        raise httpx.ReadTimeout('response lost after registration', request=request)

    app = create_proxy({'port': 8765, 'token': 'one'}, port=8766, instance_id='one', transport=httpx.MockTransport(handle))
    with TestClient(app, base_url='http://127.0.0.1:8766') as client:
        assert client.post('/api/runtime/control/view', json={'client_id': 'page'}).status_code == 503
        assert len(views) == 1
        assert client.post('/api/desktop/shutdown', json={'instance_id': 'one'}).status_code == 200
        assert not views
