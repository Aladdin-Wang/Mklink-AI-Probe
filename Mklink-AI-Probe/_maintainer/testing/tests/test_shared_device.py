import time

import pytest
from mklink import SharedDevice, connect_shared
from mklink.runtime import RuntimeErrorResponse
from test_shared_runtime import runtime


def test_failed_detach_invalidates_local_session_without_retry(monkeypatch):
    from mklink import runtime as transport
    calls = []
    def request(info, method, path, payload=None, **kwargs):
        calls.append((path, payload))
        raise RuntimeErrorResponse('detach response lost')
    monkeypatch.setattr(transport, 'request', request)
    client = transport.RuntimeClient(info={'port': 8765})
    client.session_id = 'old-session'
    with pytest.raises(RuntimeErrorResponse, match='response lost'):
        client.close()
    assert client.session_id is None
    client.close()
    with pytest.raises(RuntimeErrorResponse, match='connect first'):
        client.call('write_memory')
    with pytest.raises(RuntimeErrorResponse, match='Connect'):
        client.start_job('reset', request_id='one', confirm=True)
    assert calls == [('/_runtime/detach', {'session_id': 'old-session'})]


@pytest.mark.parametrize('detach_first,same_session,old_error', [
    (False, False, True), (False, True, True), (True, False, True), (False, False, False),
])
def test_explicit_reattach_renews_new_session_when_old_heartbeat_is_stuck(
        monkeypatch, detach_first, same_session, old_error):
    import threading
    from mklink import runtime as transport
    blocked, release, renewed = (threading.Event() for _ in range(3))
    original_wait, original_join = threading.Event.wait, threading.Thread.join
    # Compress only renewal/cleanup delays; requests still run in real threads.
    monkeypatch.setattr(threading.Event, 'wait', lambda event, timeout=None:
                        original_wait(event, .01 if timeout == 20 else timeout))
    monkeypatch.setattr(threading.Thread, 'join', lambda thread, timeout=None:
                        original_join(thread, .02 if timeout == 6 else timeout))
    attached = []
    heartbeat_threads = []
    def request(info, method, path, payload=None, **kwargs):
        if path == '/_runtime/attach':
            attached.append(str(len(attached) + 1))
            return {'session_id': '1' if same_session else attached[-1]}
        if path == '/_runtime/heartbeat':
            heartbeat_threads.append(threading.current_thread())
            if not blocked.is_set():
                blocked.set()
                assert release.wait(5)
                if old_error:
                    raise RuntimeErrorResponse('old renewal response lost')
            else:
                renewed.set()
        return {}
    monkeypatch.setattr(transport, 'request', request)
    client = transport.RuntimeClient(info={'port': 8765})
    client.connect()
    old_thread = client._heartbeat
    try:
        assert blocked.wait(2)
        if detach_first:
            client.close()
        client.connect()
        assert renewed.wait(2), 'new attachment inherited the failing old renewal'
        release.set()
        original_join(old_thread, 2)
        assert not old_thread.is_alive()
        renewed.clear()
        assert renewed.wait(2), 'old renewal failure stopped the new session'
        assert heartbeat_threads.count(old_thread) == 1
    finally:
        release.set()
        client.close()
        original_join(old_thread, 2)


@pytest.mark.parametrize('operation', ['call', 'start_job', 'connect'])
def test_client_close_waits_for_admitted_operation(monkeypatch, operation):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from mklink import runtime as transport
    entered, release, detaching, closing = (threading.Event() for _ in range(4))
    calls = []
    def request(info, method, path, payload=None, **kwargs):
        calls.append(path)
        if path == '/_runtime/detach':
            detaching.set()
        else:
            entered.set()
            assert release.wait(5)
        return {'session_id': 'old-session'}
    monkeypatch.setattr(transport, 'request', request)
    client = transport.RuntimeClient(info={'port': 8765})
    client.session_id = 'old-session'
    def invoke():
        if operation == 'call':
            return client.call('read_memory')
        if operation == 'start_job':
            return client.start_job('reset', request_id='one', confirm=True)
        return client.connect()
    def close():
        closing.set()
        client.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(invoke)
        assert entered.wait(5)
        detached = pool.submit(close)
        try:
            assert closing.wait(5)
            assert not detaching.wait(.15), 'detach overtook an admitted request'
        finally:
            release.set()
        active.result(timeout=5)
        detached.result(timeout=5)
    assert calls[-1] == '/_runtime/detach'
    assert client.session_id is None
    assert client._heartbeat is None or not client._heartbeat.is_alive()


@pytest.fixture
def shared(runtime, monkeypatch):
    client, control, calls, managers, app = runtime
    def request(info, method, path, payload=None, **kwargs):
        result = client.request(method, path, json=payload)
        if result.status_code >= 400:
            raise RuntimeErrorResponse(f'{result.status_code}: {result.text}')
        return result.json()
    monkeypatch.setattr('mklink.runtime.ensure_runtime', lambda **kwargs: control.info)
    monkeypatch.setattr('mklink.probes.select_probe', lambda _, **kwargs: {'probe_id': control.info.get('probe_id')})
    monkeypatch.setattr('mklink.runtime.request', request)
    # The SDK may not accidentally use the low-level hardware implementation.
    def forbidden(*args, **kwargs): raise AssertionError('Direct CDC must never be opened by SDK')
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge.connect', forbidden)
    return runtime


def test_shared_sdk_reads_writes_and_detaches_only_its_session(shared):
    client, control, calls, _, _ = shared
    other = client.post('/_runtime/attach', json={'kind':'mcp'}).json()['session_id']
    with connect_shared(probe='test', name='test-sdk') as device:
        assert device.read_memory(0x08005000, 4) == bytes(4)
        assert device.write_memory(0x20000000, b'\x01\x02')['verified']
        clients = client.get('/api/runtime/control/status').json()['clients']
        assert any(c['kind']=='sdk' and c['name']=='test-sdk' for c in clients)
    assert list(control.sessions) == [other]
    assert calls == ['read','write']
    with pytest.raises(RuntimeErrorResponse, match='connect first'):
        device.read_memory(0, 4)


def test_sdk_expired_session_requires_explicit_reconnect_without_replay(shared):
    _, control, calls, _, _ = shared
    with SharedDevice(probe='test') as device:
        old = device._client.session_id
        control.sessions[old].expires = 0
        with pytest.raises(RuntimeErrorResponse, match='expired'):
            device.read_memory(0,4)
        assert calls == []
        device.connect()
        assert device._client.session_id != old
        assert device.read_memory(0,4) == bytes(4)
    assert calls == ['read']


@pytest.mark.parametrize('capability', ['halt','resume','step','read_memory'])
def test_sdk_cannot_preempt_gui_capture(shared, capability):
    _, control, calls, managers, _ = shared
    managers['rtt'].running=True
    with SharedDevice(probe='test') as device:
        assert device.call('rtt_start')['reused']
        assert device.call('rtt_history')['points']
        with pytest.raises(RuntimeErrorResponse, match='409'):
            device.call(capability, {'address':'0','size':4} if capability=='read_memory' else {})
    assert calls == [] and managers['rtt'].running and not control.sessions


def test_sdk_never_retries_unknown_job_and_can_query_after_close(shared):
    _, _, calls, _, app = shared
    from fastapi import HTTPException
    @app.post('/api/device/reset')
    async def reset():
        calls.append('reset')
        raise HTTPException(500, 'transport result unknown')
    with SharedDevice(probe='test') as device:
        job=device.start_job('reset',request_id='one',confirm=True)
        for _ in range(100):
            result=device.job_status(job['job_id'])
            if result['state'] != 'running': break
            time.sleep(.01)
        assert result['state']=='unknown'
        assert device.start_job('reset',request_id='one',confirm=True)['job_id']==job['job_id']
    assert device.job_status(job['job_id'])['state']=='unknown'
    assert calls==['reset']


def test_sdk_preserves_original_exception_when_detach_fails(monkeypatch):
    device=SharedDevice()
    monkeypatch.setattr(device,'connect',lambda:device)
    def failed():raise RuntimeErrorResponse('offline')
    monkeypatch.setattr(device,'close',failed)
    with pytest.raises(ValueError, match='primary') as error:
        with device: raise ValueError('primary')
    assert 'detach failed' in error.value.__notes__[0]


def test_sdk_detach_does_not_require_python311_exception_notes(monkeypatch, caplog):
    class OldError(Exception):
        add_note = None
    device=SharedDevice()
    monkeypatch.setattr(device,'connect',lambda:device)
    def failed():raise RuntimeErrorResponse('offline')
    monkeypatch.setattr(device,'close',failed)
    with pytest.raises(OldError, match='primary'):
        with device:raise OldError('primary')
    assert 'detach failed' in caplog.text


@pytest.mark.parametrize('result', [{'data_base64':'??'}, {'data_base64':'AA=='}, {}])
def test_sdk_rejects_invalid_or_short_read_without_retry(monkeypatch, result):
    device=SharedDevice()
    calls=[]
    monkeypatch.setattr(device,'call',lambda *args: calls.append(args) or result)
    with pytest.raises(RuntimeErrorResponse, match='not retried'):
        device.read_memory(0,4)
    assert len(calls)==1


def test_sdk_write_verification_failure_is_not_replayed(monkeypatch):
    device=SharedDevice()
    calls=[]
    monkeypatch.setattr(device,'call',lambda *args: calls.append(args) or {'verified':False})
    with pytest.raises(RuntimeErrorResponse, match='verification failed'):
        device.write_memory(0,b'\x00')
    assert len(calls)==1


@pytest.mark.parametrize('job_id', ['', '../status', 'A' * 32, 123, 'a' * 33])
def test_job_query_rejects_invalid_id_without_io(monkeypatch, job_id):
    from mklink.runtime import RuntimeClient
    client = RuntimeClient(info={'port': 8765})
    def forbidden(*args, **kwargs): raise AssertionError('Invalid query reached transport')
    monkeypatch.setattr('mklink.runtime.request', forbidden)
    with pytest.raises(ValueError, match='Invalid job ID'):
        client.job_status(job_id)


def test_job_submission_requires_session_and_preserves_invalid_arguments_for_backend(shared):
    from mklink.runtime import RuntimeClient
    client = RuntimeClient()
    with pytest.raises(RuntimeErrorResponse, match='Connect'):
        client.start_job('reset', request_id='once', confirm=True)
    client.connect()
    try:
        # An empty list must not silently become {}, bypassing backend validation.
        with pytest.raises(RuntimeErrorResponse, match='422'):
            client.start_job('reset', request_id='once', confirm=True, arguments=[])
    finally:
        client.close()
