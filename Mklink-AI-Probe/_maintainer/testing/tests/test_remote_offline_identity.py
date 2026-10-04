"""Remote deployment must pass shared identity and operation admission."""
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from fastapi import Form
from mklink import runtime as sdk
from mklink.runtime import request as runtime_request
from mklink.remote.dispatcher import dispatch_capability
from mklink.remote.protocol import AgentOperationError, RequestValidationError
from mklink.remote.capabilities import CapabilityUnavailableError
from mklink.remote.shared_offline import deployment_form
from test_shared_runtime import runtime
from test_remote_shared_target import target, context
from test_remote_upstream_integration import _offline_config


@pytest.fixture
def deployment(tmp_path):
    refs = {}
    for name in ('boot.bin', 'app.bin', 'Internal.FLM'):
        p = tmp_path/name
        p.write_bytes(b'fixture')
        refs[name] = p
    uploads = SimpleNamespace(resolve=lambda reference: refs[reference])
    params = {'confirm': True, 'config': _offline_config(),
              'firmware_files': {'boot': 'boot.bin', 'app': 'app.bin'},
              'algorithm_files': {'internal': 'Internal.FLM'}}
    return params, uploads


def test_unattached_agent_has_no_direct_deployment_fallback(monkeypatch, deployment):
    params, uploads = deployment
    monkeypatch.setattr('mklink.probes._bound_probe', 'selected')
    monkeypatch.setattr('mklink.offline_download.deploy_offline_bundle', lambda *a, **k: pytest.fail('direct disk access'))
    with pytest.raises(CapabilityUnavailableError):
        dispatch_capability('offline.deploy', params, upload_manager=uploads)


def test_form_uses_only_resolved_uploads_and_does_not_mutate_request(deployment):
    params, uploads = deployment
    original = json.dumps(params)
    config = json.loads(deployment_form(params, uploads)['config_json'])
    for row in config['firmwares'] + config['algorithms']:
        assert Path(row['source_path']).is_file() and 'upload_index' not in row
    assert json.dumps(params) == original


@pytest.mark.parametrize('kind', ['firmware-path', 'algorithm-path', 'profile', 'token', 'missing', 'extra'])
def test_remote_paths_and_mismatched_refs_rejected(deployment, kind):
    params, uploads = deployment
    if kind == 'firmware-path': params['config']['firmwares'][0]['source_path'] = 'private.bin'
    if kind == 'algorithm-path': params['config']['algorithms'][0]['source_path'] = 'private.flm'
    if kind == 'profile': params['config']['algorithms'][0]['source_kind'] = 'profile'
    if kind == 'token': params['config']['algorithms'][0]['source_token'] = 'private'
    if kind == 'missing': params['firmware_files'].pop('app')
    if kind == 'extra': params['firmware_files']['extra'] = 'app.bin'
    with pytest.raises(RequestValidationError): deployment_form(params, uploads)


@pytest.mark.parametrize('blocked', [None, 'identity', 'capture', 'job'])
def test_shared_deploy_obeys_backend_admission(target, deployment, monkeypatch, blocked):
    router, http, control, calls, managers = target
    params, uploads = deployment
    received = []
    @control.app.post('/api/offline-download/deploy')
    async def deploy(config_json: str = Form(...)):
        received.append(json.loads(config_json))
        return {'deployed': True}
    def request(info, method, path, payload=None, **kwargs):
        assert kwargs.get('form') is True
        response = http.request(method, path, data=payload)
        if response.status_code >= 400:
            raise sdk.RuntimeErrorResponse(response.text, status_code=response.status_code)
        return response.json()
    monkeypatch.setattr(sdk, 'request', request)
    monkeypatch.setattr('mklink.probe_volumes.resolve_volume', lambda _: {'root': 'identity-fixture'})
    if blocked == 'identity':
        from fastapi import HTTPException
        monkeypatch.setattr(control, 'require_identity', lambda: (_ for _ in ()).throw(HTTPException(409, 'missing')))
    if blocked == 'capture': managers['rtt'].running = True
    if blocked == 'job': control.jobs.jobs['active'] = {'job_id': 'active', 'state': 'running'}
    try:
        if blocked:
            with pytest.raises(AgentOperationError) as error:
                dispatch_capability('offline.deploy', params, context(router), upload_manager=uploads, shared_target=router._target)
            assert error.value.data['status'] == 409 and not received
        else:
            assert dispatch_capability('offline.deploy', params, context(router), upload_manager=uploads, shared_target=router._target) == {'deployed': True}
            assert len(received) == 1
        assert not calls and not control.sessions
    finally:
        control.jobs.jobs.clear()


def test_form_transport_is_local_authenticated_and_never_retried(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import parse_qs
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, self.headers.get('X-Auth-Token'),
                             self.headers.get('Content-Type'),
                             self.rfile.read(int(self.headers['Content-Length'])).decode()))
            if len(requests) == 1:
                body = b'{"deployed":true}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.close_connection = True  # Accepted body, lost response; no replay.
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    info = {'port': server.server_port, 'token': 'local-fixture'}
    payload = {'config_json': json.dumps({'name': '测试 + & %'}, ensure_ascii=False)}
    try:
        assert sdk.request(info, 'POST', '/api/offline-download/deploy', payload, form=True) == {'deployed': True}
        with pytest.raises(sdk.RuntimeErrorResponse):
            sdk.request(info, 'POST', '/api/offline-download/deploy', payload, form=True)
        assert len(requests) == 2
        for path, token, content_type, body in requests:
            assert path == '/api/offline-download/deploy' and token == 'local-fixture'
            assert content_type == 'application/x-www-form-urlencoded'
            assert parse_qs(body) == {k: [v] for k, v in payload.items()}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()

@pytest.mark.parametrize('failure', ['recovery', 'generic', 'malformed', 'lost'])
def test_remote_deploy_reports_recovery_or_unknown_without_replay(target, deployment, failure, monkeypatch):
    monkeypatch.setattr(sdk, "request", runtime_request)
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    router, _, _, _, _ = target
    params, uploads = deployment
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.rfile.read(int(self.headers['Content-Length'])))
            if failure == 'lost':
                self.close_connection = True
                return
            detail = {'code': 'OFFLINE_RECOVERY_REQUIRED',
                      'recovery_directory': 'retained-fixture/backup',
                      'message': 'not-forwarded-private-diagnostic'} if failure == 'recovery' else 'private-diagnostic'
            body = json.dumps({'detail': detail}).encode() if failure != 'malformed' else b'<html>private-diagnostic</html>'
            self.send_response(500)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    original = router._target.info
    router._target.info = {'port': server.server_port, 'token': 'local-fixture'}
    try:
        with pytest.raises(AgentOperationError) as error:
            dispatch_capability('offline.deploy', params, context(router), upload_manager=uploads, shared_target=router._target)
        assert len(received) == 1
        assert error.value.data['state'] == ('recovery_required' if failure == 'recovery' else 'unknown')
        if failure == 'recovery':
            assert error.value.data['recovery_directory'] == 'retained-fixture/backup'
        else:
            assert 'recovery_directory' not in error.value.data
        assert 'private-diagnostic' not in str(error.value) + str(error.value.data)
    finally:
        router._target.info = original
        server.shutdown(); server.server_close(); thread.join(2)
        assert not thread.is_alive()
