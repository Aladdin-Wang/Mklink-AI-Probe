"""Independent profile UI shares transactions and drains before detaching."""
import asyncio
import json
import signal
import subprocess
import sys
import threading
import time

from fastapi.testclient import TestClient
import httpx
import pytest

from mklink.modbus._dashboard import ModbusDashboardServer, run_modbus_dashboard
from mklink.runtime import RuntimeErrorResponse
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory


def profile():
    return {'groups': [{'writable': True, 'registers': [
        {'addr': 4, 'min': 1, 'max': 8}, {'addr': 5, 'min': 2}]}],
        'commands': [{'action': 'level', 'write_addr': 4,
                      'params': [{'name': 'level', 'min': 1, 'max': 8}]},
                     {'action': 'reset', 'write_addr': 10, 'write_value': 42}]}


class Client:
    def __init__(self): self.calls = []
    def call(self, method, args):
        self.calls.append((method, args, time.monotonic()))
        return {'values': [17] * args.get('quantity', 0)}


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = Client()
    server = ModbusDashboardServer(client, 8, profile(), idle_timeout=0)
    with TestClient(server.app) as http:
        yield server, client, http


@pytest.mark.parametrize('path,body', [
    ('/write', {'addr': 4, 'value': True}),
    ('/write', {'addr': 4, 'value': 1.5}),
    ('/write', {'addr': '4', 'value': 2}),
    ('/write', {'addr': 4, 'value': 9}),
    ('/write', {'addr': 5, 'value': 1}),
    ('/write', {'addr': 10, 'value': 42}),
    ('/write', {'addr': 4, 'value': 2, 'extra': 1}),
    ('/command', {'action': 'level', 'params': {}}),
    ('/command', {'action': 'level', 'params': {'level': 2, 'ignored': 3}}),
    ('/command', {'action': 'level', 'params': {'level': True}}),
    ('/command', {'action': 'level', 'params': {'level': 9}}),
    ('/debug/read', {'fc': 3, 'start': 65535, 'quantity': 2}),
    ('/debug/read', {'fc': 6, 'start': 4}),
    ('/debug/write', {'fc': 6, 'start': 4, 'values': [2, 3]}),
    ('/debug/write', {'fc': 6, 'start': 4, 'values': 2}),
    ('/debug/write', {'fc': 16, 'start': 4, 'values': [2, 1]}),
    ('/debug/write', {'fc': 6, 'start': 4, 'values': [True]}),
    ('/debug/write', {'fc': 6, 'start': 4, 'values': [1.2]}),
])
def test_rejects_invalid_writes_before_transaction(dashboard, path, body):
    server, client, http = dashboard
    response = http.post(path, json={'token': server._csrf_token, **body})
    assert response.status_code == 422, response.text
    assert response.json()['ok'] is False
    assert not [call for call in client.calls if call[1]['fc'] in (5, 6, 15, 16)]


@pytest.mark.parametrize('path,body,expected', [
    ('/write', {'addr': 4, 'value': 2}, {'fc': 6, 'start': 4, 'values': [2]}),
    ('/command', {'action': 'level', 'params': {'level': 3}}, {'fc': 6, 'start': 4, 'values': [3]}),
    ('/command', {'action': 'reset'}, {'fc': 6, 'start': 10, 'values': [42]}),
    ('/debug/read', {'fc': 4, 'start': 20, 'quantity': 2}, {'fc': 4, 'start': 20, 'quantity': 2}),
    ('/debug/read', {'fc': 1, 'start': 20, 'quantity': 126}, {'fc': 1, 'start': 20, 'quantity': 126}),
    ('/debug/write', {'fc': 16, 'start': 4, 'values': [2, 3]}, {'fc': 16, 'start': 4, 'values': [2, 3]}),
])
def test_routes_use_shared_transaction_with_explicit_slave(dashboard, path, body, expected):
    server, client, http = dashboard
    response = http.post(path, json={'token': server._csrf_token, **body})
    assert response.status_code == 200 and response.json()['ok'], response.text
    assert any(call[:2] == ('modbus_transaction', {'slave': 8, **expected}) for call in client.calls)


@pytest.mark.parametrize('token,origin,status', [(None, None, 403), ('错', None, 403),
    ('valid', 'http://127.0.0.1.attacker.example', 403), ('valid', 'http://testserver:99', 403),
    ('valid', 'http://testserver', 200)])
def test_csrf_and_origin_are_checked(dashboard, token, origin, status):
    server, _, http = dashboard
    response = http.post('/write', headers={'Origin': origin} if origin else {},
                         json={'token': server._csrf_token if token == 'valid' else token or '', 'addr': 4, 'value': 2})
    assert response.status_code == status


def test_unknown_write_result_is_reported_once_without_retry(dashboard):
    server, client, http = dashboard
    original = client.call
    writes = []
    def call(method, args):
        if args['fc'] == 6:
            writes.append(args)
            raise RuntimeErrorResponse('result unknown, do not retry', status_code=504)
        return original(method, args)
    client.call = call
    events = []
    server.push_event = lambda event, payload: events.append((event, payload))
    response = http.post('/write', json={'token': server._csrf_token, 'addr': 4, 'value': 2})
    assert response.status_code == 504 and 'unknown' in response.json()['error']
    assert len(writes) == 1
    assert events == [('write_result', {'ok': False, 'error': 'result unknown, do not retry'})]


def test_template_language_and_static_files_use_captured_project(dashboard, tmp_path, monkeypatch):
    server, _, http = dashboard
    project = tmp_path / '.mklink'
    project.mkdir()
    (project / 'modbus_dashboard_template.html').write_text('__LANG__ __MAX_POINTS__ __CSRF_TOKEN__', encoding='utf-8')
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.chdir(other)
    assert http.post('/api/lang', json={'token': server._csrf_token, 'lang': 'en'}).status_code == 200
    assert json.loads((project / 'lang.json').read_text()) == {'lang': 'en'}
    assert http.get('/').text == 'en 500 ' + server._csrf_token
    assert http.get('/static/modbus_dashboard.js').status_code == 200
    assert not (other / '.mklink').exists()


def test_poll_interval_input_area_and_merged_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = {'groups': [{'registers': [{'addr': 0, 'type': 'float', 'register_type': 'input'}]},
                    {'poll_group': 'slow', 'registers': [{'addr': 8}]}]}
    client = Client()
    original = client.call
    def call(method, args):
        original(method, args)
        return {'values': [0x3f80, 0] if args['fc'] == 4 else [42]}
    client.call = call
    server = ModbusDashboardServer(client, 8, p, fast_interval=.1, slow_interval=1, idle_timeout=0)
    with TestClient(server.app) as http:
        time.sleep(.35)
        snapshot = http.get('/snapshot').json()
        assert snapshot['registers'] == {'0': 1.0, '8': 42}
    fast = [c[2] for c in client.calls if c[1]['fc'] == 4]
    assert 2 <= len(fast) <= 5
    assert all(b - a >= .09 for a, b in zip(fast, fast[1:]))
    assert len([c for c in client.calls if c[1]['fc'] == 3]) == 1


def test_stop_drains_inflight_rpc_and_skips_remaining_poll_groups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    entered, release = threading.Event(), threading.Event()
    client = Client()
    def call(method, args):
        client.calls.append(args)
        entered.set()
        assert release.wait(5)
        return {'values': [17]}
    client.call = call
    server = ModbusDashboardServer(client, 8, {'groups': [{'registers': [{'addr': 0}, {'addr': 4}]}]}, idle_timeout=0)
    server.start()
    assert entered.wait(2)
    stopper = threading.Thread(target=server.stop)
    stopper.start()
    try:
        time.sleep(.2)
        assert stopper.is_alive() and server._thread.is_alive()
        with pytest.raises(RuntimeErrorResponse, match='stopping'):
            server._transaction(6, 4, values=[42])
    finally:
        release.set()
        stopper.join(5)
        server.stop()
    assert not stopper.is_alive() and not server._thread.is_alive()
    assert len(client.calls) == 1


def test_tcp_sse_shutdown_and_disconnect_cleanup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = ModbusDashboardServer(Client(), 8, profile(), idle_timeout=0)
    port = server.start()
    async def exercise():
        async with httpx.AsyncClient(timeout=5) as http:
            async with http.stream('GET', f'http://127.0.0.1:{port}/stream') as response:
                async for line in response.aiter_lines():
                    if 'registers' in line: break
            for _ in range(100):
                if not server._bridge.client_count: break
                await asyncio.sleep(.01)
            assert not server._bridge.client_count
            async with http.stream('GET', f'http://127.0.0.1:{port}/stream') as response:
                server.request_stop()
                lines = [line async for line in response.aiter_lines()]
                assert any('shutdown' in line for line in lines)
    try:
        asyncio.run(exercise())
    finally:
        server.stop()
    assert not server._thread.is_alive() and not server._bridge.client_count


def test_poll_failure_no_fabricated_snapshot_and_runner_restores_signals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = Client()
    def call(*_): raise OSError('lost response')
    client.call = call
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, getattr(signal, 'SIGBREAK', signal.SIGTERM))}
    with pytest.raises(RuntimeErrorResponse, match='lost response'):
        run_modbus_dashboard(client, 8, profile(), no_browser=True, duration=2)
    assert all(signal.getsignal(sig) is handler for sig, handler in before.items())


@pytest.mark.parametrize('existing', [False, True])
def test_dashboard_cli_borrows_gui_and_detaches_after_http_drains(scan_cli, uart_app, monkeypatch, existing):
    cli, args, http, control, manager, _ = scan_cli
    calls = []
    monkeypatch.setattr(uart_app[3], 'read_holding_registers', lambda _, address, count, slave:
                        calls.append((slave, threading.get_ident())) or [17] * count)
    monkeypatch.setattr('mklink.modbus._profile.load_profile', lambda _: profile())
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 7, 'registers': []}).status_code == 200
    vars(args).update(slave=8, duration=.15, no_browser=True, timeout=None, retries=None)
    cli._cli_modbus_dashboard(args)
    assert calls and all(c[0] == 8 for c in calls)
    assert len({c[1] for c in calls}) == 1 and calls[0][1] != threading.get_ident()
    assert len(uart_app[3].instances) == 1 and manager.running == existing
    assert not control.sessions


def test_missing_profile_is_rejected_before_attach(scan_cli, monkeypatch):
    cli, args, *_ = scan_cli
    args.profile = 'missing-file.json'
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('opened before profile validation'))
    with pytest.raises(FileNotFoundError): cli._cli_modbus_dashboard(args)


def test_stop_waits_for_http_write_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    entered, release = threading.Event(), threading.Event()
    client = Client()
    def call(method, args):
        client.calls.append(args)
        entered.set()
        assert release.wait(5)
        return {}
    client.call = call
    # Empty poll profile isolates an in-flight write HTTP handler.
    server = ModbusDashboardServer(client, 8, {'commands': [{'action': 'reset', 'write_addr': 10, 'write_value': 42}]}, idle_timeout=0)
    port = server.start()
    results = []
    request = threading.Thread(target=lambda: results.append(httpx.post(f'http://127.0.0.1:{port}/command',
        json={'token': server._csrf_token, 'action': 'reset'}, timeout=5)))
    request.start()
    assert entered.wait(2)
    stopper = threading.Thread(target=server.stop)
    stopper.start()
    try:
        time.sleep(.2)
        assert stopper.is_alive() and request.is_alive()
    finally:
        release.set()
        request.join(5)
        stopper.join(5)
        server.stop()
    assert len(client.calls) == 1 and len(results) == 1 and results[0].json()['ok']
    assert not server._thread.is_alive() and not request.is_alive() and not stopper.is_alive()


def test_idle_shutdown_really_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    server = ModbusDashboardServer(Client(), 8, {}, idle_timeout=.1)
    server.start()
    try:
        assert server._finished.wait(3)
    finally:
        server.stop()
    assert not server._thread.is_alive()


def test_explicit_html_and_profile_precede_builtin(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'custom.html'
    path.write_text('custom page', encoding='utf-8')
    server = ModbusDashboardServer(Client(), 8, profile(), html_path=str(path))
    with TestClient(server.app) as http:
        assert http.get('/index.html').text == 'custom page'
        assert http.get('/profile').json() == profile()
        assert http.get('/csrf-token').json()['token'] == server._csrf_token


def test_arbitrary_debug_write_requires_explicit_option(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = Client()
    server = ModbusDashboardServer(client, 8, {}, allow_arbitrary_writes=True)
    with TestClient(server.app) as http:
        response = http.post('/debug/write', json={'token': server._csrf_token, 'fc': 15, 'start': 20, 'values': [True, 0]})
        assert response.status_code == 200
    assert client.calls[0][1] == {'slave': 8, 'fc': 15, 'start': 20, 'values': [True, False]}


@pytest.mark.parametrize('field,value', [('write_addr', 1.5), ('write_value', 1.5), ('write_value', '42')])
def test_profile_command_cannot_truncate_or_coerce_writes(tmp_path, monkeypatch, field, value):
    monkeypatch.chdir(tmp_path)
    client = Client()
    command = {'action': 'reset', 'write_addr': 10, 'write_value': 42, field: value}
    server = ModbusDashboardServer(client, 8, {'commands': [command]})
    with TestClient(server.app) as http:
        response = http.post('/command', json={'token': server._csrf_token, 'action': 'reset'})
        assert response.status_code == 422
    assert not client.calls


def test_base_modbus_import_does_not_require_web_dependencies():
    result = subprocess.run([sys.executable, '-c',
        "import sys; sys.modules['fastapi']=None; sys.modules['uvicorn']=None; "
        "from mklink.modbus import ModbusClient, load_profile; "
        "from mklink.modbus._session import validate_transaction; "
        "assert validate_transaction(3, 0, quantity=1) == (3, 0, 1, None)"],
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
