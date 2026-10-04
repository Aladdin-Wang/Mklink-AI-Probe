"""Agent exchange traverses the shared API, monitor, reader and raw history."""
import asyncio
import json
import threading
import pytest
import websockets

from mklink.remote.dispatcher import OperationDispatcher, dispatch_capability
from mklink.remote.protocol import AgentOperationError, RequestValidationError
from mklink.serial._monitor import SerialMonitor
from test_serial_autoreply import ports, wait_for
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory
from test_remote_capabilities import _running_agent, _request
from test_remote_client_sessions import handshake


@pytest.fixture
def shared_serial(scan_cli, ports, monkeypatch):
    monkeypatch.setattr('mklink.serial._monitor.SerialMonitor', SerialMonitor)
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    return scan_cli[2], scan_cli[3], scan_cli[3].app.state, ports


def exchange(**changes):
    return {'port': 'TEST', 'data_b64': 'UQ==', 'timeout': .1, 'confirm': True, **changes}


@pytest.mark.parametrize('existing', [False, True])
def test_agent_exchange_uses_one_reader_and_raw_gui_history(shared_serial, uart_app, monkeypatch, existing):
    http, control, _, factory = shared_serial
    manager = uart_app[2]['serial']
    if existing:
        assert http.post('/api/dash/serial/start', json={'ports': [{'port': 'TEST'}]}).status_code == 200
    original = factory.write
    def write(port, data):
        original(port, data)
        if data == b'Q': port.rx.put(b'ANSWER')
    monkeypatch.setattr(factory, 'write', write)
    assert dispatch_capability('serial.exchange', exchange()) == {'__bytes__': 'QU5TV0VS'}
    assert len(factory.instances) == 1 and not control.sessions
    assert manager.running == existing
    history = manager.get_history()
    result = manager.get_history(session=history['session'], after=0)
    entries = result['entries']
    assert b''.join(bytes.fromhex(e['hex']) for e in entries if e['direction'] == 'TX') == b'Q'
    assert b''.join(bytes.fromhex(e['hex']) for e in entries if e['direction'] == 'RX') == b'ANSWER'
    assert manager.get_ymodem_status()['state'] == 'idle'


@pytest.mark.parametrize('changes', [{'timeout': True}, {'timeout': float('inf')}, {'timeout': 6},
    {'data_b64': '?'}, {'data_b64': 'A' * 5468}, {'baudrate': 4000001}, {'port': ' '}])
def test_invalid_agent_request_never_attaches(monkeypatch, changes):
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('invalid request attached'))
    with pytest.raises(RequestValidationError):
        dispatch_capability('serial.exchange', exchange(**changes))


def test_agent_settings_conflict_leaves_gui_connection(shared_serial, uart_app):
    http, control, _, factory = shared_serial
    assert http.post('/api/dash/serial/start', json={'ports': [{'port': 'TEST', 'baudrate': 9600}]}).status_code == 200
    with pytest.raises(AgentOperationError): dispatch_capability('serial.exchange', exchange())
    assert not factory.instances[0].writes and not control.sessions
    assert uart_app[2]['serial'].running


def test_agent_list_uses_backend_without_starting_monitor(shared_serial, monkeypatch):
    http, control, _, factory = shared_serial
    monkeypatch.setattr('mklink.serial._port.list_uart_ports', lambda: [{'device': 'TEST'}])
    assert dispatch_capability('serial.list', {}) == [{'device': 'TEST'}]
    assert not control.sessions and not factory.instances


def test_two_remote_sockets_conflict_then_continue_on_same_gui_port(shared_serial, uart_app, tmp_path):
    http, control, _, factory = shared_serial
    manager = uart_app[2]['serial']
    assert http.post('/api/dash/serial/start', json={'ports': [{'port': 'TEST'}, {'port': 'OTHER'}]}).status_code == 200
    dispatcher = OperationDispatcher(tmp_path)
    async def scenario():
        async with _running_agent(request_dispatcher=dispatcher) as agent:
            async with websockets.connect(f'ws://127.0.0.1:{agent.port}') as first, \
                       websockets.connect(f'ws://127.0.0.1:{agent.port}') as second:
                await handshake(first); await handshake(second)
                await first.send(_request('serial.exchange', exchange(timeout=.3)))
                await asyncio.to_thread(wait_for, lambda: bool(factory.instances[0].writes))
                assert http.post('/api/dash/serial/stop').status_code == 409
                assert http.post('/api/dash/serial/send', json={'port': 'TEST', 'data': 'interference'}).status_code >= 400
                assert http.post('/api/dash/serial/send', json={'port': 'OTHER', 'data': 'neighbor'}).status_code == 200
                await second.send(_request('serial.exchange', exchange(timeout=.01)))
                assert 'error' in json.loads(await second.recv())
                factory.instances[0].rx.put(b'ANSWER')
                assert json.loads(await first.recv())['result'] == {'__bytes__': 'QU5TV0VS'}
                await first.close()
                await second.send(_request('serial.exchange', exchange(timeout=0), request_id=2))
                assert json.loads(await second.recv())['result'] == {'__bytes__': ''}
    try:
        asyncio.run(scenario())
        assert manager.running and not control.sessions and len(factory.instances) == 2
        assert [x[0] for x in factory.instances[0].writes] == [b'Q', b'Q']
    finally:
        dispatcher.close()


@pytest.mark.parametrize('payload', [{'data': 'z'}, {'timeout': True}, {'timeout': 6}, {'data': '00' * 4097}])
def test_api_invalid_request_does_not_write(shared_serial, payload):
    http, _, _, factory = shared_serial
    response = http.post('/api/dash/serial/exchange', json={'port': 'TEST', 'data': '51', **payload})
    assert response.status_code in (400, 422) and not factory.instances
