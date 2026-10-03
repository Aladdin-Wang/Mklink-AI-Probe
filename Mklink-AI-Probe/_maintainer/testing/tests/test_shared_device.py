import time

import pytest
from mklink import SharedDevice, connect_shared
from mklink.runtime import RuntimeErrorResponse
from test_shared_runtime import runtime


@pytest.fixture
def shared(runtime, monkeypatch):
    client, control, calls, managers, app = runtime
    def request(info, method, path, payload=None, **kwargs):
        result = client.request(method, path, json=payload)
        if result.status_code >= 400:
            raise RuntimeErrorResponse(f'{result.status_code}: {result.text}')
        return result.json()
    monkeypatch.setattr('mklink.runtime.ensure_runtime', lambda **kwargs: control.info)
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: {'probe_id': control.info.get('probe_id')})
    monkeypatch.setattr('mklink.runtime.request', request)
    monkeypatch.setattr('mklink.shared_device.request', request)
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
