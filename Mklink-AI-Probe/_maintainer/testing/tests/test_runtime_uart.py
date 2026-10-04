"""UART attachment/admission must not initialize or reserve the MCU/CDC."""
import asyncio
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastmcp import Client

from mklink.runtime import RuntimeClient
from mklink.runtime_api import install_runtime
from mklink.runtime_management import stop_backend
from test_shared_runtime import runtime, attach, call
from test_modbus_lifecycle import client_factory


def add_uart_routes(app):
    @app.get('/api/ports/uart')
    async def ports():
        return [{'device': 'TEST_UART'}]
    @app.get('/api/dash/serial/status')
    @app.get('/api/dash/modbus/status')
    async def status():
        return {'running': False}
    @app.post('/api/dash/serial/send')
    async def send(body: dict):
        return {'sent': body['data']}


def test_uart_lobby_attach_ignores_target_locks_and_never_connects(runtime):
    client, control, calls, _, app = runtime
    add_uart_routes(app)
    control.info['probe_id'] = 'lobby'
    app.state.mklink_state['device'] = None
    async def scenario():
        async with control.attach_lock, control.operation_lock:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
                response = await asyncio.wait_for(http.post('/_runtime/attach', json={'scope': 'uart'}), .5)
                assert response.status_code == 200, response.text
                return response.json()
    result = client.portal.call(scenario)
    assert result['scope'] == 'uart' and result['attached']
    assert result['capabilities'] == ['modbus_history', 'modbus_probe', 'modbus_start', 'modbus_status', 'modbus_stop', 'modbus_transaction',
                                     'serial_history', 'serial_send', 'serial_start', 'serial_status', 'serial_stop', 'uart_ports']
    assert app.state.mklink_state['device'] is None and calls == []
    session = result['session_id']
    assert call(client, session, 'uart_ports').json() == [{'device': 'TEST_UART'}]
    assert client.post('/_runtime/attach', json={}).status_code == 409
    for capability in ('halt', 'device_status', 'read_memory'):
        assert call(client, session, capability).status_code == 409
    assert client.post('/api/runtime/jobs/', json={'session_id': session,
        'action': 'reset', 'confirm': True, 'request_id': 'uart-cannot-reset'}).status_code == 409
    assert client.post('/_runtime/attach', json={'session_id': session, 'scope': 'target'}).status_code == 409
    assert not control.jobs.jobs and calls == []


@pytest.mark.parametrize('settings', [{'scope': 'unknown'}, {'scope': 'uart', 'port': 'COM9'},
                                    {'scope': 'uart', 'axf': ''}, {'scope': 'uart', 'mcu': 'F103'}])
def test_invalid_uart_attachment_has_no_effect(runtime, settings):
    client, control, calls, _, _ = runtime
    assert client.post('/_runtime/attach', json=settings).status_code == 422
    assert not control.sessions and calls == []


def test_uart_state_survives_symbol_changes_and_does_not_block_device_release(runtime):
    client, control, calls, _, app = runtime
    add_uart_routes(app)
    uart = client.post('/_runtime/attach', json={'scope': 'uart'}).json()['session_id']
    target = attach(client)
    app.state.mklink_state['device'].axf_status = {'axf_path': 'different.axf'}
    assert call(client, target, 'device_status').status_code == 409
    assert call(client, target, 'serial_status').status_code == 200
    assert call(client, uart, 'modbus_status').status_code == 200
    assert client.post('/api/device/disconnect').status_code == 409
    client.post('/_runtime/detach', json={'session_id': target})
    control.require_symbol_change()
    assert client.post('/api/runtime/control/release-device', json={'confirm': True}).status_code == 200
    assert calls == ['disconnect'] and uart in control.sessions
    assert client.post('/api/runtime/control/stop-backend', json={'confirm': True}).status_code == 409


def test_uart_mutations_do_not_take_target_admission_or_skip_authentication(runtime):
    client, control, calls, _, app = runtime
    add_uart_routes(app)
    control.info['probe_id'] = 'lobby'
    control.jobs.jobs['target-job'] = {'state': 'running', 'job_id': 'target-job'}
    async def scenario():
        async with control.operation_lock:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
                assert (await http.post('/api/dash/serial/send', json={'data': 'one'})).json() == {'sent': 'one'}
                assert (await http.post('/api/device/read-memory', json={'address': '0', 'size': 1})).status_code == 409
                assert (await http.post('/api/dash/serial/send', json={'data': 'two'},
                    headers={'X-Auth-Token': 'wrong'})).status_code == 401
                assert (await http.post('/api/dash/serial/send', json={'data': 'two'},
                    headers={'Origin': 'https://other.example'})).status_code == 403
    client.portal.call(scenario)
    assert not control.uart_operations and calls == []


def test_cancelled_uart_operation_blocks_shutdown_until_actual_completion(runtime):
    client, control, _, _, _ = runtime
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def work():
            entered.set()
            await release.wait()
        task = asyncio.create_task(control.run_operation('/api/dash/modbus/transaction', work))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        try:
            assert control.uart_operations and not control.operation_lock.locked()
            with pytest.raises(HTTPException) as caught:
                stop_backend(control, {'confirm': True})
            assert caught.value.status_code == 409 and not control.stopping
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not control.uart_operations
    client.portal.call(scenario)


def test_uart_admission_is_bounded_without_a_second_request_queue(runtime):
    client, control, _, _, _ = runtime
    async def scenario():
        release = asyncio.Event()
        tasks = [asyncio.create_task(control.run_operation('/api/dash/serial/send', release.wait)) for _ in range(64)]
        await asyncio.sleep(0)
        try:
            assert len(control.uart_operations) == 64
            with pytest.raises(HTTPException) as caught:
                await control.run_operation('/api/dash/serial/send', release.wait)
            assert caught.value.status_code == 429
        finally:
            release.set()
            await asyncio.gather(*tasks)
        assert not control.uart_operations
    client.portal.call(scenario)


def test_backend_cannot_exit_with_a_stop_pending_uart_worker(runtime):
    client, control, _, managers, _ = runtime
    managers['modbus'] = SimpleNamespace(running=False, worker_alive=True)
    response = client.post('/api/runtime/control/stop-backend', json={'confirm': True})
    assert response.status_code == 409 and not control.stopping


def test_modbus_open_and_status_do_not_block_runtime_heartbeat(client_factory, monkeypatch, tmp_path):
    from mklink.remote.api import create_app
    from mklink.remote import dashboards
    monkeypatch.setattr(dashboards, '_managers', {})
    entered, release = threading.Event(), threading.Event()
    def delayed_open(self):
        entered.set()
        assert release.wait(2)
        return True
    monkeypatch.setattr(client_factory, 'open', delayed_open)
    app = create_app(project_root=str(tmp_path))
    control = install_runtime(app, {'probe_id': 'lobby', 'port': 8765, 'token': 'test-secret', 'instance_id': 'uart'})
    control.jobs.jobs['target-job'] = {'state': 'running', 'job_id': 'target-job'}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            starting = asyncio.create_task(http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []}))
            assert await asyncio.to_thread(entered.wait, 1)
            # Backstop makes a regressed synchronous status lock fail instead of hanging pytest.
            timer = threading.Timer(1, release.set)
            timer.start()
            pending_status = asyncio.create_task(http.get('/api/dash/modbus/status'))
            start = time.monotonic()
            try:
                await asyncio.sleep(.01)
                heartbeat_started = time.monotonic()
                assert (await http.get('/_runtime/status')).status_code == 200
                elapsed = time.monotonic() - start
                assert elapsed < .5, (
                    f'elapsed={elapsed:.3f}s, scheduling={heartbeat_started-start:.3f}s, '
                    f'heartbeat={time.monotonic()-heartbeat_started:.3f}s, '
                    f'status_done={pending_status.done()}, released={release.is_set()}'
                )
                assert not pending_status.done()
            finally:
                release.set()
                timer.cancel()
                assert (await starting).status_code == 200
                await pending_status
                assert (await http.post('/api/dash/modbus/stop')).status_code == 200
            assert app.state.mklink_state['device'] is None
            assert not dashboards.get_managers()['modbus'].worker_alive
    asyncio.run(scenario())


def test_active_mcp_and_sdk_can_attach_uart_without_target(runtime, monkeypatch):
    from mklink import runtime as runtime_module, runtime_mcp
    client, control, calls, _, app = runtime
    add_uart_routes(app)
    control.info['probe_id'] = 'lobby'
    app.state.mklink_state['device'] = None
    def request(info, method, path, payload=None, **kwargs):
        response = client.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()
    monkeypatch.setattr(runtime_module, 'request', request)
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', lambda **kwargs: RuntimeClient(info=control.info, **kwargs))
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            result = await mcp.call_tool('connect', {'scope': 'uart'})
            assert result.data['scope'] == 'uart'
            assert (await mcp.call_tool('gui_call', {'capability': 'uart_ports'})).data == [{'device': 'TEST_UART'}]
            assert (await mcp.call_tool('gui_call', {'capability': 'modbus_status'})).data == {'running': False}
            await mcp.call_tool('disconnect', {})
    asyncio.run(scenario())
    assert not control.sessions and calls == [] and app.state.mklink_state['device'] is None


def test_uart_sdk_validates_before_starting_a_backend(monkeypatch):
    from mklink import runtime as module
    monkeypatch.setattr(module, 'ensure_runtime', lambda **kwargs: pytest.fail('unexpected backend startup'))
    with pytest.raises(ValueError, match='target connection settings'):
        RuntimeClient().connect(scope='uart', port='COM9')


def test_independent_uart_start_does_not_wait_for_a_bridge_start(tmp_path):
    from mklink.remote.api import start_dashboard_manager, stop_dashboard_manager_transaction
    from mklink.remote.resource_manager import ResourceManager
    state = {'resource_manager': ResourceManager()}
    entered, release = threading.Event(), threading.Event()
    class Manager:
        running = False
        def start(self): self.running = True
        def stop(self): self.running = False
    bridge, uart = Manager(), Manager()
    def slow_bridge_start():
        entered.set()
        assert release.wait(2)
        bridge.start()
    async def scenario():
        starting = asyncio.create_task(start_dashboard_manager(state, 'rtt', bridge, slow_bridge_start))
        assert await asyncio.to_thread(entered.wait, 1)
        try:
            await asyncio.wait_for(start_dashboard_manager(state, 'modbus', uart, uart.start), .5)
            assert uart.running and not bridge.running
            await asyncio.wait_for(stop_dashboard_manager_transaction(state, 'modbus', uart), .5)
            assert not uart.running and not starting.done()
        finally:
            release.set()
            await starting
            await stop_dashboard_manager_transaction(state, 'rtt', bridge)
    asyncio.run(scenario())
    assert not state['resource_manager'].get_status()


def test_resource_release_and_uart_operations_exclude_each_other(runtime):
    client, control, _, _, app = runtime
    add_uart_routes(app)
    async def scenario():
        release = asyncio.Event()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            for path, other in [('/api/resources/release-all', '/api/dash/serial/send'),
                                ('/api/dash/modbus/transaction', '/api/resources/release-all')]:
                task = asyncio.create_task(control.run_operation(path, release.wait))
                await asyncio.sleep(0)
                try:
                    assert (await http.post(other, json={'data': 'no'})).status_code == 409
                finally:
                    release.set()
                    await task
                    release.clear()
    client.portal.call(scenario)


def test_sdk_uart_selection_allows_lobby_but_preserves_explicit_probe(monkeypatch):
    from mklink import runtime as module
    starts = []
    def ensure(**kwargs):
        starts.append(kwargs)
        return {'port': 8765, 'token': 'test'}
    monkeypatch.setattr(module, 'ensure_runtime', ensure)
    monkeypatch.setattr(module, 'request', lambda info, method, path, payload, **kwargs:
        {'session_id': 'uart', 'scope': payload.get('scope')} if path.endswith('/attach') else {})
    for probe in (None, 'selected-second'):
        client = RuntimeClient(project_root='project')
        try:
            assert client.connect(scope='uart', probe=probe)['scope'] == 'uart'
        finally:
            client.close()
    assert starts == [dict(project_root='project', probe=probe, device_port=None, allow_lobby=True)
                      for probe in (None, 'selected-second')]


@pytest.mark.parametrize('path,lock_name,method,body', [
    ('serial/send', '_lifecycle_lock', 'POST', {'port': 'TEST', 'data': 'one'}),
    ('serial/status', '_ymodem_lock', 'GET', None),
    ('serial/ymodem/status', '_ymodem_lock', 'GET', None),
    ('serial/ymodem/cancel', '_lifecycle_lock', 'POST', {}),
    ('serial/ymodem/start', '_lifecycle_lock', 'POST', None),
    ('modbus/loop/start', '_lifecycle_lock', 'POST', {'fc': 3, 'start': 0, 'quantity': 1, 'count': 1}),
])
def test_uart_lock_wait_does_not_block_other_client_heartbeat(monkeypatch, tmp_path, path, lock_name, method, body):
    from mklink.remote.api import create_app
    from mklink.remote import dashboards
    monkeypatch.setattr(dashboards, '_managers', {})
    app = create_app(project_root=str(tmp_path))
    install_runtime(app, {'probe_id': 'lobby', 'port': 8765, 'token': 'test-secret', 'instance_id': 'uart'})
    manager = dashboards.get_managers()[path.split('/')[0]]
    manager._running = True
    if path.startswith('serial/'):
        manager._monitor = SimpleNamespace(port_status={}, send=lambda *args: True)
    called = threading.Event()
    method_name = {'serial/send': 'send', 'serial/status': 'get_status',
                   'serial/ymodem/status': 'get_ymodem_status', 'serial/ymodem/cancel': 'cancel_ymodem',
                   'serial/ymodem/start': 'start_ymodem', 'modbus/loop/start': 'start_loop'}[path]
    original = getattr(manager, method_name)
    def entering(*args, **kwargs):
        called.set()
        return original(*args, **kwargs)
    monkeypatch.setattr(manager, method_name, entering)
    entered, release = threading.Event(), threading.Event()
    def hold_io_lock():
        with getattr(manager, lock_name):
            entered.set()
            assert release.wait(10)
            if path == 'modbus/loop/start':
                # A concurrent close finishes before the waiting loop request.
                manager._running = False
    holder = threading.Thread(target=hold_io_lock)
    holder.start()
    assert entered.wait(1)
    timer = threading.Timer(5, release.set)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            session = (await http.post('/_runtime/attach', json={'scope': 'uart'})).json()['session_id']
            kwargs = {'json': body} if body is not None else {}
            if path == 'serial/ymodem/start':
                kwargs = {'params': {'port': 'TEST'}, 'files': {'file': ('test.bin', b'one')}}
            timer.start()
            pending = asyncio.create_task(http.request(method, '/api/dash/' + path, **kwargs))
            try:
                assert await asyncio.to_thread(called.wait, 3)
                assert (await http.post('/_runtime/heartbeat', json={'session_id': session})).status_code == 200
                # Prove progress while the manager lock is still held. The
                # watchdog only breaks a deadlock; CI scheduling is not a SLA.
                assert not release.is_set()
                assert not pending.done()
            finally:
                release.set()
                response = await pending
                expected = 409 if path in ('serial/ymodem/start', 'modbus/loop/start') else 200
                assert response.status_code == expected, response.text
                await http.post('/_runtime/detach', json={'session_id': session})
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        timer.cancel()
        holder.join(2)
        manager._running = False
        if path.startswith('serial/'):
            manager._monitor = None
    assert not holder.is_alive()


@pytest.mark.parametrize('kind', ['serial', 'modbus'])
@pytest.mark.parametrize('cancel', [False, True])
def test_uart_sse_initial_status_wait_is_async_and_subscription_is_released(kind, cancel):
    from mklink.remote.dashboards import SerialStreamManager, ModbusStreamManager
    manager = SerialStreamManager() if kind == 'serial' else ModbusStreamManager()
    entered, release = threading.Event(), threading.Event()
    lock = manager._ymodem_lock if kind == 'serial' else manager._lifecycle_lock
    def hold_io_lock():
        with lock:
            entered.set()
            assert release.wait(3)
    holder = threading.Thread(target=hold_io_lock)
    holder.start()
    assert entered.wait(1)
    timer = threading.Timer(1, release.set)
    async def scenario():
        stream = manager.sse_generator()
        pending = asyncio.create_task(anext(stream))
        timer.start()
        started = time.monotonic()
        try:
            await asyncio.sleep(.02)
            assert time.monotonic() - started < .5
            assert not pending.done() and manager._bridge.client_count == 1
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
                assert manager._bridge.client_count == 0
            else:
                release.set()
                assert 'running' in await pending
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
            await stream.aclose()
        assert manager._bridge.client_count == 0
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        timer.cancel()
        holder.join(2)
    assert not holder.is_alive()


@pytest.fixture
def uart_app(client_factory, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app
    from mklink.remote import dashboards
    from mklink.serial import _monitor
    monkeypatch.setattr(dashboards, '_managers', {})
    class Monitor:
        worker_alive = False
        sent = []
        def __init__(self, ports, **kwargs):
            self.port_status = {config['port']: 'open' for config in ports}
        def start(self): pass
        def stop(self): pass
        def send(self, port, data):
            self.sent.append((port, data))
            return True
    monkeypatch.setattr(_monitor, 'SerialMonitor', Monitor)
    monkeypatch.setattr(client_factory, 'write_register', lambda self, addr, value, slave:
                        self.calls.append(('write', addr, value, slave)), raising=False)
    app = create_app(project_root=str(tmp_path))
    control = install_runtime(app, {'probe_id': 'lobby', 'port': 8765, 'token': 'test-secret', 'instance_id': 'uart'})
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as client:
        yield client, control, dashboards.get_managers(), client_factory, Monitor
        control.sessions.clear()
        for name in ('serial', 'modbus'):
            if dashboards.get_managers()[name].running:
                assert client.post(f'/api/dash/{name}/stop').status_code == 200


def uart_attach(client):
    response = client.post('/_runtime/attach', json={'scope': 'uart'})
    assert response.status_code == 200, response.text
    return response.json()['session_id']


@pytest.mark.parametrize('stream,settings', [('serial', {'ports': [{'port': 'TEST'}]}),
                                           ('modbus', {'port': 'TEST', 'slave': 7, 'registers': []})])
def test_uart_shared_creator_borrower_and_gui_permissions(uart_app, stream, settings):
    client, control, managers, factory, monitor = uart_app
    owner, peer = uart_attach(client), uart_attach(client)
    control.jobs.jobs['target'] = {'job_id': 'target', 'state': 'running'}
    assert call(client, owner, stream + '_start', settings).status_code == 200
    assert control.created_streams[stream] == owner
    assert call(client, peer, stream + '_start', settings).status_code == 409
    assert call(client, peer, stream + '_start').json()['reused']
    assert call(client, peer, stream + '_stop').status_code == 409
    assert client.post(f'/api/dash/{stream}/stop', headers={'X-MKLink-Session': peer}).status_code == 409
    assert call(client, owner, stream + '_stop').status_code == 409
    assert client.post(f'/api/dash/{stream}/stop').status_code == 409
    if stream == 'serial':
        assert call(client, peer, 'serial_send', {'port': 'TEST', 'data': 'A'}).json() == {'ok': True}
        assert monitor.sent == [('TEST', b'A')]
    else:
        response = call(client, peer, 'modbus_transaction', {'fc': 6, 'start': 2, 'values': [17]})
        assert response.status_code == 200, response.text
        assert factory.instances[0].calls == [('write', 2, 17, 7)]
    client.post('/_runtime/detach', json={'session_id': peer})
    assert call(client, owner, stream + '_stop').status_code == 200
    assert stream not in control.created_streams and not control.sessions[owner].streams
    assert not managers[stream].worker_alive


def test_concurrent_uart_start_only_registers_the_actual_creator(uart_app, monkeypatch):
    client, control, managers, factory, _ = uart_app
    owner, peer = uart_attach(client), uart_attach(client)
    entered, release = threading.Event(), threading.Event()
    def opening(self):
        entered.set()
        assert release.wait(3)
        return True
    monkeypatch.setattr(factory, 'open', opening)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control.app),
                base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            body = {'capability': 'modbus_start', 'arguments': {'port': 'TEST', 'registers': []}}
            first = asyncio.create_task(http.post('/_runtime/call', json={**body, 'session_id': owner}))
            assert await asyncio.to_thread(entered.wait, 1)
            second = asyncio.create_task(http.post('/_runtime/call', json={**body, 'session_id': peer}))
            try:
                assert (await asyncio.wait_for(second, .5)).status_code == 409
            finally:
                release.set()
                responses = await asyncio.gather(first, second)
            assert [r.status_code for r in responses] == [200, 409]
    client.portal.call(scenario)
    assert len(factory.instances) == 1 and control.created_streams == {'modbus': owner}
    assert control.sessions[owner].streams == {'modbus'} and not control.sessions[peer].streams


def test_delayed_uart_start_response_cannot_claim_a_later_gui_session(uart_app, monkeypatch):
    client, control, managers, factory, _ = uart_app
    owner = uart_attach(client)
    original = control.invoke
    async def scenario():
        reached, release = asyncio.Event(), asyncio.Event()
        async def delayed(method, path, *args, **kwargs):
            result = await original(method, path, *args, **kwargs)
            if path == '/api/dash/modbus/start' and kwargs.get('session_id') == owner:
                reached.set()
                await release.wait()
            return result
        monkeypatch.setattr(control, 'invoke', delayed)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control.app),
                base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            request = asyncio.create_task(http.post('/_runtime/call', json={'session_id': owner,
                'capability': 'modbus_start', 'arguments': {'port': 'TEST', 'slave': 1, 'registers': []}}))
            await asyncio.wait_for(reached.wait(), 1)
            try:
                assert control.created_streams == {'modbus': owner}
                assert (await http.post('/api/dash/modbus/stop')).status_code == 409
                await http.post('/_runtime/detach', json={'session_id': owner})
                assert (await http.post('/api/dash/modbus/stop')).status_code == 200
                assert (await http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 2, 'registers': []})).status_code == 200
                assert not control.created_streams
            finally:
                release.set()
                assert (await request).status_code == 200
            assert not control.created_streams and managers['modbus'].get_status()['slave'] == 2
    client.portal.call(scenario)


def test_uart_stop_failure_keeps_ownership(uart_app, monkeypatch):
    client, control, managers, _, _ = uart_app
    owner = uart_attach(client)
    assert call(client, owner, 'modbus_start', {'port': 'TEST', 'registers': []}).status_code == 200
    original = managers['modbus'].stop
    def failing(): raise TimeoutError('still executing')
    monkeypatch.setattr(managers['modbus'], 'stop', failing)
    assert call(client, owner, 'modbus_stop').status_code == 409
    assert control.created_streams == {'modbus': owner}
    assert control.sessions[owner].streams == {'modbus'}
    monkeypatch.setattr(managers['modbus'], 'stop', original)
    assert call(client, owner, 'modbus_stop').status_code == 200


@pytest.mark.parametrize('stream,settings', [('serial', {'ports': [{'port': 'TEST'}]}),
                                           ('modbus', {'port': 'TEST', 'registers': []})])
def test_uart_operator_stop_reuses_ownership_guard_during_target_job(uart_app, stream, settings):
    client, control, managers, _, _ = uart_app
    owner = uart_attach(client)
    assert call(client, owner, stream + '_start', settings).status_code == 200
    control.jobs.jobs['target'] = {'job_id': 'target', 'state': 'running'}
    path = '/api/runtime/control/stop-acquisition'
    body = {'stream': stream, 'confirm': True}
    assert client.post(path, json={'stream': stream}).status_code == 422
    assert client.post(path, json=body).status_code == 409
    assert managers[stream].running
    client.post('/_runtime/detach', json={'session_id': owner})
    assert client.post(path, json=body).status_code == 200
    assert not managers[stream].worker_alive and not control.created_streams


def test_uart_mcp_shared_writes_use_existing_workers(uart_app, monkeypatch):
    from mklink import runtime as runtime_module, runtime_mcp
    client, control, managers, factory, monitor = uart_app
    def request(info, method, path, payload=None, **kwargs):
        response = client.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()
    monkeypatch.setattr(runtime_module, 'request', request)
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', lambda **kwargs: RuntimeClient(info=control.info, **kwargs))
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            assert (await mcp.call_tool('connect', {'scope': 'uart'})).data['scope'] == 'uart'
            for capability, arguments in [
                ('serial_start', {'ports': [{'port': 'TEST_SERIAL'}]}),
                ('serial_send', {'port': 'TEST_SERIAL', 'data': '0041ff', 'hex': True}),
                ('modbus_start', {'port': 'TEST_MODBUS', 'slave': 7, 'registers': []}),
                ('modbus_transaction', {'fc': 6, 'start': 2, 'values': [17]}),
                ('serial_stop', {}), ('modbus_stop', {})]:
                result = await mcp.call_tool('gui_call', {'capability': capability, 'arguments': arguments})
                assert not result.is_error, result
            await mcp.call_tool('disconnect', {})
    asyncio.run(scenario())
    assert monitor.sent == [('TEST_SERIAL', b'\x00A\xff')]
    assert len(factory.instances) == 1 and factory.instances[0].calls == [('write', 2, 17, 7)]
    assert not control.sessions and not control.created_streams
    assert all(not managers[name].worker_alive for name in ('serial', 'modbus'))
    assert control.app.state.mklink_state['device'] is None


def test_detach_during_uart_open_does_not_create_a_ghost_session(uart_app, monkeypatch):
    client, control, managers, factory, _ = uart_app
    owner = uart_attach(client)
    entered, release = threading.Event(), threading.Event()
    def opening(self):
        entered.set()
        assert release.wait(3)
        return True
    monkeypatch.setattr(factory, 'open', opening)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control.app),
                base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            starting = asyncio.create_task(http.post('/_runtime/call', json={'session_id': owner,
                'capability': 'modbus_start', 'arguments': {'port': 'TEST', 'registers': []}}))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                assert (await http.post('/_runtime/detach', json={'session_id': owner})).status_code == 200
            finally:
                release.set()
                assert (await starting).status_code == 200
    client.portal.call(scenario)
    assert not control.sessions and managers['modbus'].running
    assert call(client, owner, 'modbus_stop').status_code == 409
    assert client.post('/api/runtime/control/stop-acquisition', json={'stream': 'modbus', 'confirm': True}).status_code == 200
    assert not control.created_streams and not managers['modbus'].worker_alive


def test_failed_uart_start_never_registers_an_owner(uart_app, monkeypatch):
    client, control, managers, factory, _ = uart_app
    owner = uart_attach(client)
    monkeypatch.setattr(factory, 'open', lambda self: False)
    response = call(client, owner, 'modbus_start', {'port': 'TEST', 'registers': []})
    assert response.status_code == 409, response.text
    assert not control.created_streams and not control.sessions[owner].streams
    assert not managers['modbus'].worker_alive


def test_modbus_per_request_slave_does_not_change_the_shared_connection(uart_app):
    client, control, managers, factory, _ = uart_app
    owner = uart_attach(client)
    assert call(client, owner, 'modbus_start', {'port': 'TEST', 'slave': 7, 'registers': []}).status_code == 200
    for slave in (8, None, 9, None):
        arguments = {'fc': 6, 'start': 2, 'values': [17]}
        if slave is not None:
            arguments['slave'] = slave
        result = call(client, owner, 'modbus_transaction', arguments)
        assert result.status_code == 200, result.text
        assert result.json()['slave'] == (slave or 7)
    assert factory.instances[0].calls == [('write', 2, 17, slave) for slave in (8, 7, 9, 7)]
    assert managers['modbus'].get_status()['slave'] == 7


@pytest.mark.parametrize('extra', [{'slvae': 8}, {'timeout': .15}, {'retries': 0},
                                 {'slave': True}, {'slave': 0}, {'slave': 248}, {'slave': '8'}])
def test_modbus_transaction_rejects_unsupported_or_invalid_settings_before_io(uart_app, extra):
    client, _, _, factory, _ = uart_app
    owner = uart_attach(client)
    assert call(client, owner, 'modbus_start', {'port': 'TEST', 'registers': []}).status_code == 200
    arguments = {'fc': 6, 'start': 2, 'values': [17], **extra}
    assert call(client, owner, 'modbus_transaction', arguments).status_code in (400, 422)
    assert client.post('/api/dash/modbus/transaction', json=arguments).status_code in (400, 422)
    assert factory.instances[0].calls == []
