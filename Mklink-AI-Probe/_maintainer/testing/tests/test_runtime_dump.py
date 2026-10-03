"""Shared dump contracts reuse the actual route, parser and admission gate."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import Mock

import pytest
from fastmcp import Client
from mklink import dump_memory, runtime_mcp
from mklink.runtime import RuntimeClient, RuntimeErrorResponse
from test_runtime_memory import batch
from test_dump_memory_session import FakeBridge, _b1_frame, _old_regions_frame


def test_shared_route_assembles_real_b1_blocks_and_confirms_stop(batch):
    client,state,device,_,_=batch
    payload=bytes(range(256))*16
    bridge=FakeBridge([_b1_frame(1,payload[:2048],block_index=0,block_count=2,total_size=4096),
                       _b1_frame(2,payload[2048:],block_index=1,block_count=2,total_size=4096)])
    device._bridge=bridge
    response=client.post('/api/device/dump-memory',json={'regions':[{'address':0x08000000,'size':4096}]})
    assert response.status_code==200,response.text
    assert bytes.fromhex(response.json()['samples'][0]['regions'][0]['data_hex'])==payload
    writes=[c[1] for c in bridge.calls if c[0]=='write']
    assert writes==[b'cmd.dump_memory(0x08000000, 4096, 0)\n',b'cmd.dump_memory(0x08000000, 1, -1.0)\n']
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('overrides',[{'regions':[]},{'regions':[{'address':True,'size':4}]},
    {'regions':[{'address':-1,'size':4}]},{'regions':[{'address':2**32,'size':4}]},{'regions':[{'address':0,'size':True}]},
    {'regions':[{'address':2**64-1,'size':2}]},{'regions':[{'address':0,'size':524289}]},
    {'regions':[{'address':0,'size':1}]*9},{'regions':[{'address':0,'size':4,'extra':1}]},
    {'regions':[{'address':0,'size':4096}],'sample_count':129},
    {'regions':[{'address':0,'size':524288}],'sample_count':2},
    {'sample_count':True},{'sample_count':0},{'timeout':True},{'timeout':0},{'timeout':61},
    {'speed_profile':'unknown'},{'extra':True}])
def test_dump_validates_entire_request_before_clock_or_capture(batch,monkeypatch,overrides):
    client,_,device,_,_=batch
    read=Mock();monkeypatch.setattr(dump_memory,'read_dump_memory_regions_once',read)
    device.set_debug_speed=Mock()
    response=client.post('/api/device/dump-memory',json={'regions':[{'address':0,'size':4}],'speed_profile':'low',**overrides})
    assert response.status_code==422,response.text
    read.assert_not_called();device.set_debug_speed.assert_not_called()


@pytest.mark.parametrize('failure',['crc','stop'])
def test_bad_crc_or_unconfirmed_stop_is_failure_without_sample_replay(batch,failure):
    client,state,device,_,_=batch
    frame=_old_regions_frame(1,[(0,b'abcd')])
    if failure=='crc': frame=frame[:-1]+bytes([frame[-1]^255])
    bridge=FakeBridge([frame]);device._bridge=bridge
    if failure=='stop': bridge._stop_stream_and_sync=Mock(return_value=False)
    response=client.post('/api/device/dump-memory',json={'regions':[{'address':0,'size':4}],'sample_count':2})
    assert response.status_code==500,response.text
    assert sum(c==('write',b'cmd.dump_memory(0x00000000, 4, 0)\n') for c in bridge.calls)==1
    assert not state['resource_manager'].get_status()


def test_shared_dump_does_not_preempt_gui_or_change_clock(batch,monkeypatch):
    client,_,device,_,managers=batch
    managers['rtt'].running=True
    read=Mock();monkeypatch.setattr(dump_memory,'read_dump_memory_regions_once',read)
    device.set_debug_speed=Mock()
    response=client.post('/api/device/dump-memory',json={'regions':[{'address':0,'size':4}],'speed_profile':'low'})
    assert response.status_code==409 and managers['rtt'].running
    read.assert_not_called();device.set_debug_speed.assert_not_called()


def test_shared_dump_holds_operation_and_lease_for_all_samples(batch,monkeypatch):
    client,state,device,control,_=batch
    entered,release=threading.Event(),threading.Event()
    def read(*args,**kwargs):
        entered.set();assert release.wait(5);return (b'abcd',)
    reader=Mock(side_effect=read)
    monkeypatch.setattr(dump_memory,'read_dump_memory_regions_once',reader)
    with ThreadPoolExecutor() as pool:
        result=pool.submit(client.post,'/api/device/dump-memory',json={'regions':[{'address':0,'size':4}],'sample_count':2})
        assert entered.wait(5)
        try:
            assert control.operation_lock.locked() and state['resource_manager'].get_status()
            assert client.post('/api/dash/rtt/start',json={}).status_code==409
        finally: release.set()
        response=result.result(timeout=5)
    assert response.status_code==200 and response.json()['sample_count']==2
    assert reader.call_count==2
    assert not control.operation_lock.locked() and not state['resource_manager'].get_status()


def test_runtime_budget_covers_explicit_samples_and_never_retries(monkeypatch):
    calls=[]
    def request(*args,**kwargs):
        calls.append(kwargs)
        raise RuntimeErrorResponse('response lost')
    monkeypatch.setattr('mklink.runtime.request',request)
    client=RuntimeClient(info={'port':8765});client.session_id='one'
    with pytest.raises(RuntimeErrorResponse,match='lost'):
        client.call('dump_memory',{'regions':[{'address':0,'size':4}],'sample_count':2,'timeout':60})
    assert calls==[{'timeout':145}]
    with pytest.raises(ValueError):
        client.call('dump_memory',{'regions':[{'address':0,'size':4}],'sample_count':65})
    assert len(calls)==1


def test_active_mcp_dump_is_shared_thin_adapter(monkeypatch):
    calls=[]
    class FakeClient:
        info={}
        def __init__(self,**kwargs): calls.append('new')
        def connect(self,**kwargs): return {}
        def call(self,name,arguments): calls.append((name,arguments));return {'sample_count':1}
        def close(self):pass
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',FakeClient)
    body={'regions':[{'address':0,'size':4}]}
    async def run():
        async with Client(runtime_mcp.build_server()) as mcp:
            assert (await mcp.call_tool('dump_memory',body,raise_on_error=False)).is_error
            assert not calls
            await mcp.call_tool('connect',{'probe':'chosen'})
            assert not (await mcp.call_tool('dump_memory',body)).is_error
    asyncio.run(run())
    assert calls==['new',('dump_memory',{**body,'sample_count':1,'timeout':10.0,'speed_profile':None})]


@pytest.mark.parametrize('options', [
    {'period':-1},{'period':True},{'duration':301},{'duration':True},
    {'frames':True},{'frames':100001},{'frames':0,'duration':0},{'period':0,'frames':2},
    {'speed_profile':'bad'},{'regions':[{'address':0,'size':4}]*16},
])
def test_periodic_capture_invalid_arguments_never_start_or_change_clock(batch,options):
    client,_,device,_,_=batch
    device.set_debug_speed=Mock()
    device._bridge=Mock()
    response=client.post('/api/device/dump-memory/capture',json={'regions':[{'address':0,'size':4}],**options})
    assert response.status_code==422,response.text
    device.set_debug_speed.assert_not_called()
    device._bridge._enter_stream.assert_not_called()


def test_periodic_capture_assembles_each_sample_and_ignores_extra_queued_samples(batch):
    client,_,device,_,_=batch
    raw=b''.join(_b1_frame(t,value*2048,block_index=i,block_count=2,total_size=4096)
                 for t,value,i in ((1,b'A',0),(2,b'A',1),(3,b'B',0),(4,b'B',1),(5,b'C',0),(6,b'C',1)))
    device._bridge=FakeBridge([raw])
    response=client.post('/api/device/dump-memory/capture',json={'regions':[{'address':0,'size':4096}], 'period':.001,'frames':2})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['sample_count']==2 and result['total_bytes']==8192 and result['stopped_by']=='frames'
    assert [bytes.fromhex(s['regions'][0]['data_hex']) for s in result['samples']]==[b'A'*4096,b'B'*4096]
    assert device._bridge.calls[-1]==('exit',)


@pytest.mark.parametrize('case',['missing_first','duplicate_first','crc','limit','stop'])
def test_periodic_capture_never_succeeds_with_incomplete_or_unconfirmed_data(batch,monkeypatch,case):
    client,state,device,_,_=batch
    first=_b1_frame(1,b'A'*2048,block_index=0,block_count=2,total_size=4096)
    last=_b1_frame(2,b'A'*2048,block_index=1,block_count=2,total_size=4096)
    raw=last if case=='missing_first' else first+first+last if case=='duplicate_first' else first+last
    if case=='crc':raw=raw[:-1]+bytes([raw[-1]^255])
    device._bridge=FakeBridge([raw])
    if case=='limit':monkeypatch.setattr(dump_memory,'MAX_DUMP_RESULT_JSON_BYTES',20)
    if case=='stop':device._bridge._stop_stream_and_sync=Mock(return_value=False)
    response=client.post('/api/device/dump-memory/capture',json={'regions':[{'address':0,'size':4096}],'period':.001,'frames':1})
    assert response.status_code== (422 if case=='limit' else 500),response.text
    assert not state['resource_manager'].get_status()
    assert sum(c==('write',b'cmd.dump_memory(0x00000000, 4096, 0.001)\n') for c in device._bridge.calls)==1


def test_periodic_capture_duration_reports_only_complete_samples_and_partial_tail(monkeypatch):
    from types import SimpleNamespace
    good=_b1_frame(1,b'A'*2048,block_index=0,block_count=2,total_size=4096)+_b1_frame(2,b'A'*2048,block_index=1,block_count=2,total_size=4096)
    tail=_b1_frame(3,b'B'*2048,block_index=0,block_count=2,total_size=4096)
    ticks=iter([0,0,.1,1])
    monkeypatch.setattr(dump_memory.time,'monotonic',lambda:next(ticks))
    result=dump_memory.capture_dump_stream(SimpleNamespace(_bridge=FakeBridge([good+tail])),[{'address':0,'size':4096}],period=.01,frames=0,duration=.25)
    assert result['sample_count']==1 and result['incomplete_tail'] and result['stopped_by']=='duration'


def test_periodic_capture_startup_does_not_consume_collection_window(monkeypatch):
    from types import SimpleNamespace
    ticks=iter([0,.5,.5,.6,.9])
    monkeypatch.setattr(dump_memory.time,'monotonic',lambda:next(ticks))
    bridge=FakeBridge([_old_regions_frame(1,[(0,b'AAAA')]),_old_regions_frame(2,[(0,b'BBBB')])])
    result=dump_memory.capture_dump_stream(SimpleNamespace(_bridge=bridge),[{'address':0,'size':4}],period=.01,frames=0,duration=.25)
    assert result['sample_count']==2 and result['stopped_by']=='duration'


def test_periodic_capture_busy_rejects_without_stopping_gui(batch):
    client,_,device,_,managers=batch
    managers['rtt'].running=True
    device._bridge=Mock()
    response=client.post('/api/device/dump-memory/capture',json={'regions':[{'address':0,'size':4}]})
    assert response.status_code==409 and managers['rtt'].running
    device._bridge._enter_stream.assert_not_called()


def test_periodic_transport_budget_covers_count_only_request(monkeypatch):
    call=Mock(return_value={})
    monkeypatch.setattr('mklink.runtime.request',call)
    client=RuntimeClient(info={'port':8765});client.session_id='one'
    client.call('capture_dump',{'regions':[{'address':0,'size':4}],'period':.001,'frames':10,'duration':0})
    assert call.call_args.kwargs['timeout']==320
