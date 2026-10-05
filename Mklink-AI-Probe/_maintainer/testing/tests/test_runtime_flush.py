"""Flush writes share the hardware gate, bounded planner and fail-stop semantics."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastmcp import Client

from mklink import cli, runtime_cli, runtime_mcp
from mklink.device import Device, DeviceError
from mklink.memory_write import execute_flush, flush_command, plan_flush_batches, validate_writes
from mklink.runtime import RuntimeClient, RuntimeErrorResponse
from test_runtime_memory import batch  # Existing real runtime/API fixture.



def _flush_session(batch):
    from mklink.runtime_api import Session
    _,state,device,control,_=batch
    control.sessions['flush']=Session(state['project_root'], device.axf_status.get('axf_path'),
                                     symbol_version=control.symbol_version())
    return 'flush'


@pytest.mark.parametrize('spaced', [False, True])
def test_shared_envelope_accepts_full_decoded_flush_capacity(batch, spaced):
    from test_shared_runtime import call
    client,_,device,_,_=batch
    device._bridge.send_command=Mock(return_value='')
    device.read_memory=Mock(side_effect=lambda address,size: b'\xa5'*size)
    data=('a5 ' if spaced else 'a5')*12288
    response=call(client,_flush_session(batch),'flush_memory',{'writes':[{'address':0x20000000,'data_hex':data}],'verify':True})
    assert response.status_code==200,response.text
    assert response.json()['ok'] and response.json()['verified']
    assert response.json()['total_bytes']==12288
    device._bridge.send_command.assert_called_once()
    assert device.read_memory.call_count==3


@pytest.mark.parametrize('capability,args', [
    ('flush_memory', {'writes':[{'address':0,'data_hex':'aa'*12289}]}),
    ('flush_memory', {'writes':[{'address':0,'data_hex':' '*50000}]}),
    ('read_memory', {'address':0,'size':4,'padding':'x'*17000}),
])
def test_shared_envelope_rejects_excess_without_io(batch,capability,args):
    from test_shared_runtime import call
    client,_,device,_,_=batch
    device._bridge.send_command=Mock()
    response=call(client,_flush_session(batch),capability,args)
    assert response.status_code==422,response.text
    device._bridge.send_command.assert_not_called()
    device.read_memory.assert_not_called()


@pytest.mark.parametrize('writes', [None, [], [{'address':0, 'data_hex':'00'}]*9,
    [{'address':True,'data_hex':'00'}], [{'address':1.5,'data_hex':'00'}],
    [{'address':'1','data_hex':'00'}], [{'address':0xffffffff,'data_hex':'0011'}],
    [{'address':0,'data_hex':''}], [{'address':0,'data_hex':'xx'}],
    [{'address':0,'data_hex':'00','extra':True}],
    [{'address':0,'data_hex':'00'*12289}],
    [{'address':0,'data_hex':'0011'},{'address':1,'data_hex':'22'}]])
def test_invalid_whole_request_does_not_write(batch, writes):
    client, state, device, _, _ = batch
    device._bridge.send_command = Mock()
    response = client.post('/api/device/flush-memory', json={'writes':writes})
    assert response.status_code == 422, response.text
    device._bridge.send_command.assert_not_called()
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('response', ['flush fail', 'flush fail: bus fault', 'TypeError: failed', 'unknown output', None])
def test_first_error_stops_all_later_batches(response):
    device = SimpleNamespace(_bridge=SimpleNamespace(send_command=Mock(return_value=response)), read_memory=Mock())
    parsed = validate_writes([{'address':0x20000000,'data_hex':bytes(range(90)).hex()}])
    result = execute_flush(device, parsed, verify=True)
    assert not result['ok'] and not result['verified'] and result['batches'] == 3
    assert len(result['results']) == 1
    device._bridge.send_command.assert_called_once()
    device.read_memory.assert_not_called()


@pytest.mark.parametrize('readback', [b'', b'\xff'*30, TimeoutError('lost readback')])
def test_readback_failure_never_replays_or_sends_next_batch(readback):
    device = SimpleNamespace(_bridge=SimpleNamespace(send_command=Mock(return_value='')),
                             read_memory=Mock(side_effect=readback if isinstance(readback, Exception) else None,
                                              return_value=readback))
    parsed = validate_writes([{'address':0,'data_hex':bytes(range(90)).hex()}])
    if isinstance(readback, Exception):
        with pytest.raises(TimeoutError): execute_flush(device, parsed, verify=True)
    else:
        assert not execute_flush(device, parsed, verify=True)['ok']
    device._bridge.send_command.assert_called_once()
    device.read_memory.assert_called_once()


def test_device_write_uses_common_planner_and_reports_errors():
    device = Device()
    device._connected = True
    device._bridge = SimpleNamespace(send_command=Mock(return_value='flush fail'))
    with pytest.raises(DeviceError, match='no remaining batches'):
        device.write_memory(0, bytes(range(90)))
    device._bridge.send_command.assert_called_once()


def test_exact_limit_compact_write_and_bounded_verified_reads():
    device = SimpleNamespace(_bridge=SimpleNamespace(send_command=Mock(return_value='cmd.flush_memory([...])\n')),
                             read_memory=Mock(return_value=b'\xa5'*4096))
    parsed = validate_writes([{'address':0x20000000,'data_hex':'a5'*12288}])
    result = execute_flush(device, parsed, verify=True)
    assert result['ok'] and result['verified'] and result['batches'] == 1
    assert device.read_memory.call_count == 3
    assert 'bytes([0xA5])*12288' in device._bridge.send_command.call_args.args[0]
    varied = validate_writes([{'address':0xffffd000,'data_hex':(bytes(range(256))*48).hex()}])
    batches = plan_flush_batches(varied)
    assert sum(len(data) for batch in batches for _,data in batch) == 12288
    assert all(len(batch) <= 8 and len(flush_command(batch)) <= 230 for batch in batches)


def test_gui_capture_rejects_write_without_stopping_and_idle_write_verifies(batch):
    client, state, device, _, managers = batch
    device._bridge.send_command = Mock(return_value='')
    body = {'writes':[{'address':0,'data_hex':'00010203'}]}
    managers['rtt'].running = True
    assert client.post('/api/device/flush-memory',json=body).status_code == 409
    assert managers['rtt'].running
    device._bridge.send_command.assert_not_called()
    managers['rtt'].running = False
    response = client.post('/api/device/flush-memory',json=body)
    assert response.status_code == 200 and response.json()['verified']
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('extra', [{'verify':1},{'stop':True}])
def test_invalid_options_before_io(batch, extra):
    client,_,device,_,_=batch
    device._bridge.send_command=Mock()
    assert client.post('/api/device/flush-memory',json={'writes':[{'address':0,'data_hex':'00'}],**extra}).status_code==422
    device._bridge.send_command.assert_not_called()


@pytest.mark.parametrize('failure', [False, True])
def test_cli_shared_entry_verifies_and_never_continues_failed_repeat(monkeypatch,failure):
    calls=[]
    class FakeClient:
        def __init__(self,**kwargs): pass
        def connect(self,**kwargs): calls.append(('connect',kwargs))
        def call(self,name,args): calls.append((name,args)); return {'ok':not failure,'verified':not failure}
        def close(self): calls.append(('detach',None))
    monkeypatch.setattr(runtime_cli,'RuntimeClient',FakeClient)
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge',lambda *a,**kw:pytest.fail('CLI opened CDC'))
    monkeypatch.setattr(sys,'argv',['mklink','flush-memory','0x20000000:AA*64','--probe','chosen','--repeat','2'])
    if failure:
        with pytest.raises(SystemExit,match='remaining writes'): cli.main()
    else: cli.main()
    assert calls[0][1]['probe']=='chosen' and calls[-1]==('detach',None)
    writes=[args for name,args in calls if name=='flush_memory']
    assert len(writes)==(1 if failure else 2)
    assert writes[0]=={'writes':[{'address':0x20000000,'data_hex':'aa'*64}], 'verify':True}


def test_cli_rejects_huge_repeat_before_allocating_or_connecting(monkeypatch):
    monkeypatch.setattr(runtime_cli,'RuntimeClient',lambda **kw:pytest.fail('unexpected connection'))
    monkeypatch.setattr(sys,'argv',['mklink','flush-memory','0:AA*999999999999999'])
    with pytest.raises(SystemExit,match='1..12288'): cli.main()


def test_runtime_budget_covers_each_batch_without_retry(monkeypatch):
    request=Mock(return_value={'ok':True})
    monkeypatch.setattr('mklink.runtime.request',request)
    client=RuntimeClient()
    client.session_id='session'
    client.info={}
    client.call('flush_memory',{'writes':[{'address':0,'data_hex':bytes(range(90)).hex()}]})
    request.assert_called_once()
    assert request.call_args.kwargs['timeout']>=75


def test_mcp_connect_required_and_one_shared_call(monkeypatch):
    calls=[]
    class FakeClient:
        info={}
        def __init__(self,**kwargs): calls.append('new')
        def connect(self,**kwargs): return {}
        def call(self,name,args): calls.append((name,args)); return {'ok':True,'verified':True}
        def close(self): pass
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',FakeClient)
    body={'writes':[{'address':0,'data_hex':'00'}]}
    async def run():
        async with Client(runtime_mcp.build_server()) as mcp:
            assert (await mcp.call_tool('flush_memory',body,raise_on_error=False)).is_error
            assert not calls
            await mcp.call_tool('connect',{'probe':'selected'})
            assert not (await mcp.call_tool('flush_memory',body)).is_error
    asyncio.run(run())
    assert calls==['new',('flush_memory',{**body,'verify':True})]
