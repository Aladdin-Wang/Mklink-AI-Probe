"""Agent Modbus reaches the shared worker, never a private serial provider."""
import asyncio
import json
import threading
from contextlib import contextmanager
import pytest
import websockets

from mklink.remote.dispatcher import OperationDispatcher, dispatch_capability
from mklink.remote.protocol import AgentOperationError, RequestValidationError
from mklink.remote.capabilities import CapabilityUnavailableError
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory
from test_remote_capabilities import _running_agent, _request
from test_remote_client_sessions import handshake


@pytest.fixture(autouse=True)
def isolated_inventory(monkeypatch):
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('kind,fc,value', [('holding', 3, None), ('register', 6, 17),
    ('registers', 16, [17, 18]), ('coil', 5, True), ('coils', 15, [True, False])])
def test_agent_transactions_share_worker_and_leave_gui_defaults(scan_cli, uart_app,
                                                               monkeypatch, existing, kind, fc, value):
    _, _, http, control, manager, _ = scan_cli
    factory = uart_app[3]
    calls = []
    def execute(self, address, values, slave):
        calls.append((address, values, slave, threading.get_ident()))
        return [17, 18] if fc == 3 else None
    method = {3: 'read_holding_registers', 6: 'write_register', 16: 'write_registers',
              5: 'write_coil', 15: 'write_coils'}[fc]
    monkeypatch.setattr(factory, method, execute, raising=False)
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 7,
            'timeout': .7, 'retries': 2, 'registers': []}).status_code == 200
    params = {'port': 'TEST', 'kind': kind, 'address': 2, 'count': 2,
              'slave': 8, 'value': value, 'confirm': True}
    operation = 'modbus.read' if fc == 3 else 'modbus.write'
    assert dispatch_capability(operation, params) == ([17, 18] if fc == 3 else {'written': True})
    assert [item[:3] for item in calls] == [(2, 2 if fc == 3 else value, 8)]
    assert calls[0][3] != threading.get_ident()
    assert len(factory.instances) == 1 and not control.sessions
    assert manager.running == existing
    if existing:
        status = manager.get_status()
        assert status['slave'] == 7 and status['connection']['timeout'] == .7
        assert status['connection']['retries'] == 2
    else:
        assert factory.instances[0].closed and not manager.worker_alive
        assert factory.instances[0].options['retries'] == 0


@pytest.mark.parametrize('existing', [False, True])
def test_agent_scan_uses_shared_probe_once_per_address(scan_cli, existing):
    _, _, http, control, manager, calls = scan_cli
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []}).status_code == 200
    assert dispatch_capability('modbus.scan', {'port': 'TEST', 'start': 1, 'end': 3}) == [2]
    assert [item[:2] for item in calls] == [(1, 0), (2, 0), (3, 0)]
    assert manager.running == existing and not control.sessions


@pytest.mark.parametrize('operation,change,field', [
    ('read', {'port': ' '}, 'port'), ('read', {'kind': 'input'}, 'kind'),
    ('read', {'slave': 248}, 'slave'), ('read', {'count': 126}, 'count'),
    ('read', {'address': 65536}, 'address'), ('read', {'timeout': True}, 'timeout'),
    ('read', {'timeout': float('inf')}, 'timeout'),
    ('write', {'kind': 'register', 'value': 65536}, 'value'),
    ('write', {'kind': 'coils', 'value': [True, 1]}, 'value'),
    ('write', {'kind': 'registers', 'value': []}, 'value'),
    ('scan', {'end': 248}, 'range'), ('scan', {'address': 65536}, 'address')])
def test_invalid_request_never_attaches(monkeypatch, operation, change, field):
    from mklink import runtime
    monkeypatch.setattr(runtime, 'RuntimeClient', lambda **_: pytest.fail('invalid request attached'))
    params = {'port': 'TEST', 'kind': 'holding', 'address': 0, 'confirm': True, **change}
    with pytest.raises(RequestValidationError) as error:
        dispatch_capability('modbus.' + operation, params)
    assert error.value.as_error()['data']['field'] == field


@pytest.mark.parametrize('change', [{'port': 'OTHER'}, {'timeout': .2}, {'baudrate': 19200}])
def test_conflict_does_not_reconfigure_or_issue_io(scan_cli, change):
    _, _, http, control, manager, _ = scan_cli
    assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []}).status_code == 200
    before = manager.get_status()['connection']
    with pytest.raises(AgentOperationError, match='Shared Modbus'):
        dispatch_capability('modbus.read', {'port': 'TEST', 'kind': 'holding', 'address': 0, **change})
    assert manager.running and not control.sessions
    assert manager.get_status()['connection'] == before
    assert not manager.get_status()['latest']


def test_unknown_write_is_not_replayed_and_releases_owned_session(scan_cli, uart_app, monkeypatch):
    _, _, _, control, manager, _ = scan_cli
    calls = []
    def write(*args):
        calls.append(args)
        raise TimeoutError('synthetic unknown result')
    monkeypatch.setattr(uart_app[3], 'write_register', write, raising=False)
    with pytest.raises(AgentOperationError, match='do not retry'):
        dispatch_capability('modbus.write', {'port': 'TEST', 'kind': 'register',
            'address': 0, 'value': 17, 'confirm': True})
    assert len(calls) == 1 and not control.sessions and not manager.running


def test_real_remote_sockets_use_same_gui_worker(scan_cli, uart_app, tmp_path):
    _, _, http, control, manager, _ = scan_cli
    assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []}).status_code == 200
    dispatcher = OperationDispatcher(tmp_path)
    async def scenario():
        async with _running_agent(request_dispatcher=dispatcher) as agent:
            async with websockets.connect(f'ws://127.0.0.1:{agent.port}') as first, \
                       websockets.connect(f'ws://127.0.0.1:{agent.port}') as second:
                await handshake(first)
                await handshake(second)
                for socket in (first, second):
                    await socket.send(_request('modbus.read', {'port': 'TEST',
                        'kind': 'holding', 'address': 0, 'count': 1}))
                    response = json.loads(await socket.recv())
                    assert 'result' in response, response
                await first.close()
                await second.send(_request('modbus.scan', {'port': 'TEST', 'start': 2, 'end': 2}, request_id=2))
                assert json.loads(await second.recv())['result'] == [2]
    try:
        asyncio.run(scenario())
        assert manager.running and not control.sessions
        assert len(uart_app[3].instances) == 1
    finally:
        dispatcher.close()


@pytest.mark.parametrize('requested,expected', [(0, .05), (99, 10.0)])
def test_explicit_timeout_retains_bounds_for_new_connection(scan_cli, uart_app, requested, expected):
    dispatch_capability('modbus.read', {'port': 'TEST', 'kind': 'holding',
        'address': 0, 'timeout': requested})
    assert uart_app[3].instances[0].options['timeout'] == expected


def test_dispatcher_uses_configured_probe_not_remote_selection(monkeypatch, tmp_path):
    from mklink import uart_session
    from mklink.remote.agent import AgentDispatchContext
    from mklink.remote.resource_manager import ResourceManager
    seen = []
    probes = [{'probe_id': 'usb-original', 'port': 'configured-probe', 'alias': '', 'identity_stable': True}]
    monkeypatch.setattr('mklink.probes.inventory', lambda: probes)
    @contextmanager
    def session(connection, **options):
        seen.append(options)
        class Client:
            def call(self, name, payload): return {'values': [42]}
        yield Client()
    monkeypatch.setattr(uart_session, 'modbus_session', session)
    dispatcher = OperationDispatcher(tmp_path, runtime_probe='configured-probe')
    try:
        assert dispatcher('modbus.read', {'port': 'TEST', 'kind': 'holding',
            'address': 0, 'probe': 'remote-other'}, AgentDispatchContext(
                device=None, resource_manager=ResourceManager(), client_id='connection-a')) == [42]
        probes[:] = [{'probe_id': 'usb-neighbor', 'port': 'configured-probe', 'alias': '', 'identity_stable': True}]
        dispatcher('modbus.read', {'port': 'TEST', 'kind': 'holding', 'address': 0},
                   AgentDispatchContext(device=None, resource_manager=ResourceManager(), client_id='connection-a'))
        assert seen == [{'scan': False, 'project_root': tmp_path.resolve(),
            'probe': 'usb-original', 'kind': 'sdk', 'name': 'Agent Modbus connection-a'}] * 2
    finally:
        dispatcher.close()


def test_socket_disconnect_waits_for_worker_before_detaching(scan_cli, uart_app, monkeypatch, tmp_path):
    _, _, _, control, manager, _ = scan_cli
    entered, release, detached = threading.Event(), threading.Event(), threading.Event()
    def read(*args):
        entered.set()
        assert release.wait(5)
        return [42]
    monkeypatch.setattr(uart_app[3], 'read_holding_registers', read)
    dispatcher = OperationDispatcher(tmp_path)
    async def scenario():
        async with _running_agent(request_dispatcher=dispatcher,
                                  client_closed=lambda _: detached.set()) as agent:
            async with websockets.connect(f'ws://127.0.0.1:{agent.port}') as socket:
                await handshake(socket)
                await socket.send(_request('modbus.read', {'port': 'TEST',
                    'kind': 'holding', 'address': 0}))
                try:
                    assert await asyncio.to_thread(entered.wait, 2)
                    await socket.close()
                    assert manager.running and len(control.sessions) == 1
                    assert not detached.is_set()
                finally:
                    release.set()
                assert await asyncio.to_thread(detached.wait, 3)
                assert not control.sessions and not manager.running
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        dispatcher.close()


@pytest.mark.parametrize('available', [False, True])
def test_missing_or_unstable_configured_probe_never_attaches(monkeypatch, tmp_path, available):
    from mklink import runtime
    monkeypatch.setattr('mklink.probes.inventory', lambda: [
        {'probe_id': 'local-unstable', 'port': 'configured-probe', 'alias': '',
         'identity_stable': False}] if available else [])
    monkeypatch.setattr(runtime, 'RuntimeClient', lambda **_: pytest.fail('identity failure attached'))
    dispatcher = OperationDispatcher(tmp_path, runtime_probe='configured-probe')
    try:
        with pytest.raises(CapabilityUnavailableError):
            dispatcher('modbus.read', {'port': 'TEST', 'kind': 'holding', 'address': 0}, None)
    finally:
        dispatcher.close()


def test_explicit_uart_lobby_does_not_enumerate_or_become_a_target(monkeypatch):
    from mklink.probes import select_probe
    from mklink.runtime import RuntimeErrorResponse
    monkeypatch.setattr('mklink.probes.inventory', lambda: pytest.fail('UART lobby enumerated probes'))
    assert select_probe('lobby', allow_lobby=True)['probe_id'] == 'lobby'
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    with pytest.raises(RuntimeErrorResponse):
        select_probe('lobby')


def test_bound_probe_disappearance_does_not_use_reassigned_com(scan_cli, monkeypatch, tmp_path):
    _, _, _, control, manager, _ = scan_cli
    probes = [{'probe_id': 'usb-original', 'port': 'COM99', 'alias': '', 'identity_stable': True}]
    monkeypatch.setattr('mklink.probes.inventory', lambda: probes)
    dispatcher = OperationDispatcher(tmp_path, runtime_probe='COM99')
    try:
        assert dispatcher._shared_probe() == 'usb-original'
        probes[:] = [{'probe_id': 'usb-neighbor', 'port': 'COM99', 'alias': '', 'identity_stable': True}]
        with pytest.raises(AgentOperationError):
            dispatcher('modbus.read', {'port': 'TEST', 'kind': 'holding', 'address': 0}, None)
        assert not control.sessions and not manager.running
        assert dispatcher._shared_probe() == 'usb-original'
    finally:
        dispatcher.close()
