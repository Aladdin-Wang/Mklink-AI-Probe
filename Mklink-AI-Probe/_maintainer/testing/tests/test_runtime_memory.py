"""Batch memory shares the real API gate and existing Device range coalescing."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from mklink import SharedDevice, runtime_mcp
from mklink.device import Device
from mklink.remote.api import create_app
from mklink.runtime import RuntimeErrorResponse
from mklink.runtime_api import install_runtime


@pytest.fixture
def batch(monkeypatch, tmp_path):
    managers = {name: SimpleNamespace(running=False) for name in ('rtt','superwatch','systemview','vofa','serial','modbus')}
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: managers)
    app = create_app(project_root=str(tmp_path))
    state = app.state.mklink_state
    device = Device(project_root=str(tmp_path))
    device._connected = True
    device._bridge = SimpleNamespace(state=None)
    device.read_memory = Mock(side_effect=lambda address,size: bytes((address+i)&255 for i in range(size)))
    device.close = Mock()
    state['device'] = device
    control = install_runtime(app, {'port':8765,'token':'fixture','instance_id':'fixture'})
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token':'fixture'}) as client:
        yield client, state, device, control, managers
        state['device'] = None


def test_real_device_coalesces_touching_regions_only_and_preserves_order(batch):
    client,state,device,_,_ = batch
    response=client.post('/api/device/read-memory-regions',json={'regions':[
        {'address':0x20000004,'size':4}, {'address':0x20000000,'size':4},
        {'address':0x20000101,'size':2}, {'address':0x20000002,'size':2}]})
    assert response.status_code == 200, response.text
    assert [row['hex'] for row in response.json()['regions']] == ['04050607','00010203','0102','0203']
    assert response.json()['total_bytes']==12
    assert [call.args for call in device.read_memory.call_args_list]==[(0x20000000,8),(0x20000101,2)]
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('regions', [None, [], {}, [None], [{'address':0}],
    [{'address':True,'size':4}], [{'address':'0','size':4}], [{'address':0,'size':True}],
    [{'address':0,'size':1.5}], [{'address':-1,'size':4}], [{'address':0xffffffff,'size':2}],
    [{'address':0,'size':0}], [{'address':0,'size':4097}], [{'address':0,'size':4,'extra':1}],
    [{'address':0,'size':1}]*17, [{'address':0,'size':4096},{'address':4096,'size':1}]])
def test_all_regions_validated_before_any_read(batch, regions):
    client,state,device,_,_=batch
    body={'regions':[{'address':0,'size':4}]+regions} if isinstance(regions,list) and regions else {'regions':regions}
    response=client.post('/api/device/read-memory-regions',json=body)
    assert response.status_code==422,response.text
    device.read_memory.assert_not_called()
    assert not state['resource_manager'].get_status()


def test_unknown_fields_rejected_and_exact_4096_byte_boundary_allowed(batch):
    client,_,device,_,_=batch
    assert client.post('/api/device/read-memory-regions',json={'regions':[{'address':0,'size':4}],'halt':True}).status_code==422
    device.read_memory.assert_not_called()
    response=client.post('/api/device/read-memory-regions',json={'regions':[{'address':0xfffff000,'size':4096}]})
    assert response.status_code==200 and response.json()['total_bytes']==4096
    device.read_memory.assert_called_once_with(0xfffff000,4096)


@pytest.mark.parametrize('failure',[b'', TimeoutError('lost response')])
def test_incomplete_or_failed_hardware_is_not_replayed(batch,failure):
    client,state,device,_,_=batch
    if isinstance(failure,Exception): device.read_memory.side_effect=failure
    else: device.read_memory.side_effect=lambda *args:failure
    response=client.post('/api/device/read-memory-regions',json={'regions':[{'address':0,'size':4},{'address':16,'size':4}]})
    assert response.status_code==500
    assert device.read_memory.call_count==1
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('payloads',[[],[b''],[b'1234',b'5678'],['1234']])
def test_service_rejects_invalid_device_batch_shape(batch,payloads):
    client,_,device,_,_=batch
    device.read_memory_regions=Mock(return_value=payloads)
    response=client.post('/api/device/read-memory-regions',json={'regions':[{'address':0,'size':4}]})
    assert response.status_code==500 and 'Incomplete' in response.text
    device.read_memory_regions.assert_called_once()


def test_busy_capture_rejects_batch_without_stopping_gui(batch):
    client,_,device,_,managers=batch
    managers['rtt'].running=True
    assert client.post('/api/device/read-memory-regions',json={'regions':[{'address':0,'size':4}]}).status_code==409
    device.read_memory.assert_not_called()
    assert managers['rtt'].running


def test_batch_keeps_gate_and_lease_until_worker_finishes(batch):
    client,state,device,control,_=batch
    entered,release=threading.Event(),threading.Event()
    def read(*args):
        entered.set()
        assert release.wait(5)
        return bytes(4)
    device.read_memory.side_effect=read
    body={'regions':[{'address':0,'size':4}]}
    with ThreadPoolExecutor() as pool:
        pending=pool.submit(client.post,'/api/device/read-memory-regions',json=body)
        assert entered.wait(5)
        try:
            assert control.operation_lock.locked() and state['resource_manager'].get_status()
            assert client.post('/api/device/read-memory-regions',json=body).status_code==409
            assert client.post('/api/dash/rtt/start',json={}).status_code==409
        finally: release.set()
        assert pending.result(timeout=5).status_code==200
    assert not control.operation_lock.locked() and not state['resource_manager'].get_status()
    assert device.read_memory.call_count==1


def test_mcp_batch_requires_connect_and_forwards_one_request(monkeypatch):
    calls=[]
    class FakeClient:
        info={}
        def __init__(self,**kwargs): calls.append('new')
        def connect(self,**kwargs): return {}
        def call(self,name,arguments): calls.append((name,arguments)); return {'regions':[]}
        def close(self): pass
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',FakeClient)
    body={'regions':[{'address':0,'size':4}]}
    async def run():
        async with Client(runtime_mcp.build_server()) as mcp:
            assert (await mcp.call_tool('read_memory_regions',body,raise_on_error=False)).is_error
            assert not calls
            await mcp.call_tool('connect',{'probe':'chosen'})
            assert not (await mcp.call_tool('read_memory_regions',body)).is_error
    asyncio.run(run())
    assert calls==['new',('read_memory_regions',body)]


@pytest.mark.parametrize('response', [{}, {'regions':None,'region_count':1,'total_bytes':4},
    {'regions':[{'address':'0x00000000','size':4,'hex':'00'}],'region_count':1,'total_bytes':4},
    {'regions':[{'address':'0x00000004','size':4,'hex':'00000000'}],'region_count':1,'total_bytes':4}])
def test_sdk_invalid_response_is_not_replayed(monkeypatch,response):
    sdk=SharedDevice()
    call=Mock(return_value=response)
    monkeypatch.setattr(sdk,'call',call)
    with pytest.raises(RuntimeErrorResponse,match='not retried'): sdk.read_memory_regions([(0,4)])
    call.assert_called_once()


def test_sdk_batch_bytes_and_invalid_input(monkeypatch):
    sdk=SharedDevice()
    call=Mock(return_value={'regions':[{'address':'0x00000000','size':2,'hex':'0102'}],'region_count':1,'total_bytes':2})
    monkeypatch.setattr(sdk,'call',call)
    assert sdk.read_memory_regions([(0,2)])==[b'\x01\x02']
    call.assert_called_once_with('read_memory_regions',{'regions':[{'address':0,'size':2}]})
    call.reset_mock()
    for invalid in (None,[],[(0,)],[(True,4)],[(0,4097)]):
        with pytest.raises(ValueError): sdk.read_memory_regions(invalid)
    call.assert_not_called()
