"""Agent target clients share backend admission and release only their sessions."""
import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import websockets
from mklink import runtime as sdk
from mklink.remote.agent import AgentConfig, AgentDispatchContext, SiteAgent
from mklink.remote.dispatcher import OperationDispatcher
from mklink.remote.protocol import AgentOperationError, RequestValidationError
from mklink.remote.capabilities import CapabilityUnavailableError
from test_shared_runtime import runtime, attach
from test_remote_capabilities import _request
from test_remote_client_sessions import handshake


@pytest.fixture
def target(runtime, monkeypatch, tmp_path):
    http, control, calls, managers, app = runtime
    def request(info, method, path, payload=None, **kwargs):
        response = http.request(method, path, json=payload)
        if response.status_code >= 400:
            raise sdk.RuntimeErrorResponse(response.text, status_code=response.status_code)
        return response.json()
    monkeypatch.setattr(sdk, 'request', request)
    monkeypatch.setattr(sdk, 'ensure_runtime', lambda **_: control.info)
    router = OperationDispatcher(tmp_path)
    monkeypatch.setattr(router._target, 'select_probe', lambda: 'usb-' + 'a'*24)
    router.connect_target()
    try:
        yield router, http, control, calls, managers
    finally:
        router.close()


def context(router, name='first'):
    return AgentDispatchContext(router._target, None, name)


def test_sessions_are_per_client_and_gui_survives_disconnect(target):
    router, http, control, calls, _ = target
    gui = attach(http)
    for name in ('first', 'second'):
        result = router.dispatch('memory.read', {'address': '0x20000000', 'size': '0x4'}, context(router, name))
        assert result == {'__bytes__': 'AAAAAA=='}
    assert len(control.sessions) == 3
    router.client_closed('first')
    assert len(control.sessions) == 2 and gui in control.sessions
    router.dispatch('probe.info', {}, context(router, 'second'))
    router.close()
    assert list(control.sessions) == [gui] and calls == ['read', 'read']


@pytest.mark.parametrize('size', [0, 4097, True, -1])
def test_invalid_memory_never_reaches_hardware(target, size):
    router, _, _, calls, _ = target
    with pytest.raises((AgentOperationError, RequestValidationError)):
        router.dispatch('memory.read', {'address': 0, 'size': size}, context(router))
    assert not calls


def test_capture_blocks_target_without_direct_fallback(target):
    router, _, _, calls, managers = target
    managers['rtt'].running = True
    with pytest.raises(AgentOperationError) as error:
        router.dispatch('memory.read', {'address': 0, 'size': 4}, context(router))
    assert error.value.data['status'] == 409 and not calls
    managers['rtt'].running = False
    assert router.dispatch('memory.read', {'address': 0, 'size': 4}, context(router))


def test_confirmation_and_identity_required(target):
    router, _, control, calls, _ = target
    with pytest.raises(RequestValidationError):
        router.dispatch('memory.write', {'address': 0, 'data_b64': 'AQ=='}, context(router))
    with pytest.raises(CapabilityUnavailableError):
        router.dispatch('probe.info', {}, context(router, None))
    assert not control.sessions and not calls
    assert router.dispatch('memory.write', {'address': 0, 'data_b64': 'AQ==', 'confirm': True}, context(router)) == {'written': 1}
    assert calls == ['write']


@pytest.mark.parametrize('failure', ['submit', 'poll'])
def test_unknown_job_keeps_identifiers_and_never_replays(target, monkeypatch, failure):
    router, _, _, _, _ = target
    client = router._target._client('first')
    submit = Mock(return_value={'job_id': 'job-fixture', 'state': 'running'})
    poll = Mock(side_effect=sdk.RuntimeErrorResponse('lost response'))
    if failure == 'submit': submit.side_effect = sdk.RuntimeErrorResponse('lost response')
    monkeypatch.setattr(client, 'start_job', submit)
    monkeypatch.setattr(client, 'job_status', poll)
    with pytest.raises(AgentOperationError) as error:
        router.dispatch('target.reset', {'confirm': True, 'request_id': 'explicit-id'}, context(router))
    assert error.value.data['request_id'] == 'explicit-id'
    assert error.value.data['job_id'] == ('job-fixture' if failure == 'poll' else None)
    assert submit.call_count == 1 and poll.call_count == (failure == 'poll')


@pytest.mark.parametrize('operation', ['rtt.read', 'systemview.read'])
def test_shared_streams_require_explicit_subscription(target, operation):
    router, _, control, _, _ = target
    assert router.capabilities()['stream.'+operation.split('.')[0]].available is True
    with pytest.raises(RequestValidationError):
        router.dispatch(operation, {}, context(router))
    assert not control.sessions


def test_actual_agent_sockets_share_target_and_disconnect_independently(target):
    router, http, control, calls, _ = target
    gui = attach(http)
    async def scenario():
        agent = SiteAgent(AgentConfig(port=0), router.connect_target,
            capability_provider=router.capabilities, request_dispatcher=router.dispatch,
            client_closed=router.client_closed)
        serving = asyncio.create_task(agent.serve())
        try:
            for _ in range(100):
                if agent.ready: break
                await asyncio.sleep(.01)
            async with websockets.connect(f'ws://127.0.0.1:{agent.port}') as first, websockets.connect(f'ws://127.0.0.1:{agent.port}') as second:
                await handshake(first)
                await handshake(second)
                await first.send(_request('agent.reconnect'))
                assert 'result' in json.loads(await first.recv())
                retained = {'job_id': 'b'*32, 'request_id': 'socket-lost', 'state': 'unknown'}
                control.jobs.jobs[retained['job_id']] = retained
                await second.send(_request('jobs.status', {'request_id': 'socket-lost'}, request_id=10))
                assert json.loads(await second.recv())['result'] == retained
                assert list(control.sessions) == [gui] and not calls
                for socket in (first, second):
                    await socket.send(_request('memory.read', {'address': 0, 'size': 4}, request_id=2))
                    assert json.loads(await socket.recv())['result'] == {'__bytes__': 'AAAAAA=='}
                assert len(control.sessions) == 3
                await first.close()
                for _ in range(100):
                    if len(control.sessions) == 2: break
                    await asyncio.sleep(.01)
                assert len(control.sessions) == 2 and gui in control.sessions
                await second.send(_request('probe.info', request_id=3))
                assert json.loads(await second.recv())['result']['connected']
        finally:
            agent.request_stop()
            await asyncio.wait_for(serving, 3)
    asyncio.run(scenario())
    assert list(control.sessions) == [gui] and calls == ['read', 'read']

@pytest.mark.parametrize('operation,params,capability,arguments,response,expected', [
    ('idcode', {}, 'device_status', {}, {'connected': True, 'idcode': '0x1234'}, 0x1234),
    ('mcu_name', {}, 'device_status', {}, {'connected': True, 'mcu': 'test'}, 'test'),
    ('target.halt', {}, 'halt', {}, {'halted': True}, {'halted': True}),
    ('target.resume', {}, 'resume', {}, {'halted': False}, {'halted': False}),
    ('target.step', {}, 'step', {}, {'halted': True}, {'halted': True}),
    ('registers.core', {}, 'core_registers', {}, {'registers': {'r0': 7}}, {'r0': 7}),
    ('register.read', {'name': 'SCB.CFSR'}, 'read_register', {'name': 'SCB.CFSR'}, {'value': 7}, 7),
    ('variable.read', {'name': 'tick'}, 'read_variable', {'name': 'tick'}, {'value': 9}, 9),
    ('variable.write', {'name': 'tick', 'value': 9, 'confirm': True}, 'write_variable', {'name': 'tick', 'value': 9}, {}, {'written': True}),
    ('breakpoint.set', {'address': '0x8005000'}, 'breakpoints', {'action': 'set', 'target': '0x8005000'}, {'slot': 2}, {'slot': 2}),
    ('breakpoint.clear', {'slot': 2}, 'breakpoints', {'action': 'clear', 'slot': 2}, {'cleared': [2]}, {'cleared': True}),
    ('breakpoint.clear_all', {}, 'breakpoints', {'action': 'clear_all'}, {'cleared': [1, 2]}, {'cleared': 2}),
    ('symbols.status', {}, 'device_status', {}, {'axf': {'loaded': True}}, {'loaded': True}),
    ('symbols.memory_map', {}, 'memory_map', {}, {'ram': []}, {'ram': []}),
    ('symbols.list', {}, 'symbol_catalog', {'q': '', 'writable': False, 'offset': 0, 'limit': 200}, {'items': []}, {'items': []}),
    ('symbols.search', {'query': 'tick', 'limit': 2}, 'symbol_catalog', {'q': 'tick', 'writable': False, 'offset': 0, 'limit': 2}, {'items': []}, {'items': []}),
    ('hardfault.check', {}, 'hardfault_check', {}, {'cfsr': 1}, {'cfsr': 1}),
    ('hardfault.decode', {'fault_regs': {'cfsr': 1}}, 'hardfault_decode', {'fault_regs': {'cfsr': 1}}, {'fault': True, 'cfsr': 1}, {'cfsr': 1}),
    ('hardfault.decode', {}, 'hardfault_decode', {}, {'fault': None}, None),
])
def test_core_adapter_uses_existing_capabilities(target, monkeypatch, operation, params, capability, arguments, response, expected):
    router, _, _, _, _ = target
    calls = []
    client = router._target._client('first')
    def call(name, args=None):
        calls.append((name, args or {}))
        return response
    monkeypatch.setattr(client, 'call', call)
    assert router.dispatch(operation, {**params, 'confirm': True}, context(router)) == expected
    assert calls == [(capability, arguments)]


@pytest.mark.parametrize('operation,params,action,arguments,expected', [
    ('flash.program', {'firmware': 'opaque', 'board': 'example', 'reset_after': False}, 'flash', {'firmware': 'test.bin', 'board': 'example', 'reset_after': False}, {'success': True}),
    ('flash.erase_chip', {'target_part': 'exact'}, 'erase', {'target_part': 'exact'}, True),
    ('flash.erase_sector', {'address': '0x8005000', 'algorithm_id': 'chosen'}, 'erase_sector', {'address': 0x8005000, 'algorithm_id': 'chosen'}, True),
    ('target.reset', {}, 'reset', {}, {'reset': True}),
])
def test_target_jobs_forward_options_and_poll_once(target, monkeypatch, operation, params, action, arguments, expected):
    router, _, _, _, _ = target
    monkeypatch.setattr(router._uploads, 'resolve', lambda _: 'test.bin')
    client = router._target._client('first')
    submit = Mock(return_value={'job_id': 'j1', 'state': 'running'})
    poll = Mock(return_value={'job_id': 'j1', 'state': 'succeeded', 'result': {'success': True}})
    monkeypatch.setattr(client, 'start_job', submit)
    monkeypatch.setattr(client, 'job_status', poll)
    assert router.dispatch(operation, {**params, 'confirm': True, 'request_id': 'id1'}, context(router)) == expected
    submit.assert_called_once_with(action, request_id='id1', confirm=True, arguments=arguments)
    poll.assert_called_once_with('j1')


def test_new_catalog_and_fault_capabilities_use_actual_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app
    from mklink.runtime_api import install_runtime
    from test_remote_api import _connected_symbol_device
    app = create_app(auth_token=None, project_root=str(tmp_path))
    device, _ = _connected_symbol_device(tmp_path)
    device.decode_hardfault = Mock(return_value=None)
    device.check_hardfault = Mock(return_value={'SCB.CFSR': 1})
    app.state.mklink_state['device'] = device
    control = install_runtime(app, {'port': 8765, 'token': 'test-secret', 'instance_id': 'fault-fixture'})
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    try:
        with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            session = attach(http)
            def call(name, args):
                return http.post('/_runtime/call', json={'session_id': session, 'capability': name, 'arguments': args})
            catalog = call('symbol_catalog', {'q': 'gain', 'limit': 1})
            assert catalog.status_code == 200, catalog.text
            assert catalog.json()['items'][0]['path'] == 'gain'
            assert call('hardfault_check', {}).json() == {'SCB.CFSR': 1}
            assert call('hardfault_decode', {'fault_regs': {'SCB.CFSR': 1}}).json()['fault'] is None
            device.decode_hardfault.assert_called_once_with({'SCB.CFSR': 1})
            assert call('hardfault_decode', {'fault_regs': {'SCB.CFSR': True}}).status_code == 422
            assert device.decode_hardfault.call_count == 1
            assert http.get('/api/device/hardfault-detail').json()['fault'] is None
            device.decode_hardfault.assert_called_with()
    finally:
        app.state.mklink_state['device'] = None


def test_symbol_parse_detaches_only_caller_and_preserves_other_clients(target, monkeypatch):
    from fastapi import HTTPException
    router, http, control, calls, _ = target
    @control.app.post('/api/device/parse-axf')
    async def parse(body: dict):
        if control.sessions:
            raise HTTPException(409, 'other target clients attached')
        calls.append('parse')
        return {'loaded': True}
    monkeypatch.setattr(router._uploads, 'resolve', lambda _: 'fixture.axf')
    router.dispatch('probe.info', {}, context(router, 'first'))
    router.dispatch('probe.info', {}, context(router, 'second'))
    other = router._target._clients['second'].session_id
    with pytest.raises(AgentOperationError) as error:
        router.dispatch('symbols.parse', {'source': 'opaque'}, context(router, 'first'))
    assert error.value.data['status'] == 409
    assert list(control.sessions) == [other] and not calls
    router.client_closed('second')
    assert router.dispatch('symbols.parse', {'source': 'opaque'}, context(router, 'first')) == {'loaded': True}
    assert not control.sessions and calls == ['parse']
    router.dispatch('probe.info', {}, context(router, 'first'))
    assert len(control.sessions) == 1


def test_job_query_uses_retained_records_without_target_attach(target, monkeypatch):
    router, http, control, calls, _ = target
    job = {'job_id': 'a'*32, 'request_id': 'lost-response', 'state': 'unknown',
           'probe_id': control.info.get('probe_id'), 'result': None}
    control.jobs.jobs[job['job_id']] = job
    monkeypatch.setattr(router._target, '_client', Mock(side_effect=AssertionError('must not attach')))
    for params in ({'job_id': job['job_id']}, {'request_id': job['request_id']}):
        assert router.dispatch('jobs.status', params, context(router)) == job
    assert not control.sessions and not calls
    assert len(control.jobs.jobs) == 1 and not control.jobs.tasks
    with pytest.raises(AgentOperationError) as error:
        router.dispatch('jobs.status', {'request_id': 'absent'}, context(router))
    assert error.value.data['state'] == 'not_found'
    assert not calls


@pytest.mark.parametrize('params', [{}, {'job_id': '../'}, {'request_id': ''},
    {'request_id': True}, {'request_id': 'x'*129}, {'request_id': 'x', 'job_id': 'a'*32},
    {'request_id': 'x', 'confirm': True}])
def test_job_query_rejects_bad_selectors_without_io(target, params):
    router, _, control, calls, _ = target
    with pytest.raises(RequestValidationError):
        router.dispatch('jobs.status', params, context(router))
    assert not control.sessions and not calls
