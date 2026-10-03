"""Periodic measurement uses shared admission and real wire sample validation."""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastmcp import Client
from mklink import cli, dump_benchmark, runtime_cli, runtime_mcp
from mklink.dump_memory import DumpMemoryStreamSession
from mklink.runtime import RuntimeClient, RuntimeErrorResponse
from test_runtime_memory import batch
from test_dump_memory_session import FakeBridge, _b1_frame, _b1_regions_frame, _old_regions_frame


def wire_samples(size=4096, tail=False):
    frames=[]
    for ts in (0,100000,200000,300000,400000):
        if size <= 2048:
            frames.append(_old_regions_frame(ts,[(0,b'a'*size)]))
        else:
            for index in (0,1):
                frames.append(_b1_frame(ts+index*1000,b'a'*min(2048,size-index*2048),
                                       block_index=index,block_count=2,total_size=size))
    if tail:
        frames.append(_b1_frame(500000,b'a'*2048,block_index=0,block_count=2,total_size=size))
    return b''.join(frames)


def clock(monkeypatch, ticks=(0,.1,.1,3)):
    values=iter(ticks)
    monkeypatch.setattr(dump_benchmark,'time',SimpleNamespace(monotonic=lambda:next(values),sleep=lambda _:None))


@pytest.mark.parametrize('size',[4,2048,4096])
def test_actual_api_wire_parser_and_measurement(batch,monkeypatch,size):
    client,state,device,_,_=batch
    device._bridge=FakeBridge([wire_samples(size)])
    device._bridge._ctx=SimpleNamespace(swd_clock_hz=30000000)
    clock(monkeypatch)
    result=client.post('/api/device/dump-memory/measure',json={'regions':[{'address':0,'size':size}],'duration':1})
    assert result.status_code==200,result.text
    r=result.json()
    assert r['samples']==3 and r['sample_hz']==10 and r['payload_bytes_per_second']==size*10
    assert r['median_interval_us']==r['p99_interval_us']==r['max_interval_us']==100000
    assert not r['incomplete_tail'] and r['clock_hz']==30000000
    assert device._bridge.calls[-1]==('exit',)
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('body',[
    {'regions':[]},{'regions':[{'address':0,'size':1}]*16},
    {'regions':[{'address':True,'size':4}]},{'regions':[{'address':0,'size':True}]},
    {'regions':[{'address':0xffffffff,'size':4}]},{'regions':[{'address':0,'size':4097}]},
    {'regions':[{'address':0,'size':4,'other':1}]},{'duration':0},{'duration':31},
    {'period':0},{'period':.2},{'speed_profile':'unknown'},{'stop':True},
])
def test_validation_precedes_clock_or_capture(batch,body):
    client,_,device,_,_=batch
    device._bridge=Mock();device.set_debug_speed=Mock()
    response=client.post('/api/device/dump-memory/measure',json={'regions':[{'address':0,'size':4}],'speed_profile':'low',**body})
    assert response.status_code==422,response.text
    device._bridge._enter_stream.assert_not_called();device.set_debug_speed.assert_not_called()


@pytest.mark.parametrize('case',['crc','block_crc','missing_first','coverage','wrong_total','regressed','stop'])
def test_measurement_does_not_report_success_for_corrupt_or_unconfirmed_data(batch,monkeypatch,case):
    client,state,device,_,_=batch
    raw=wire_samples()
    if case=='crc': raw=raw[:-1]+bytes([raw[-1]^255])
    if case=='block_crc': raw=_b1_regions_frame(0,[(0,b'a'*2048)],block_index=0,block_count=2,total_size=4096,corrupt_block_crc=True)
    if case=='missing_first': raw=_b1_frame(0,b'a'*2048,block_index=1,block_count=2,total_size=4096)
    if case=='coverage': raw=_b1_regions_frame(0,[(1,b'a'*2048)],block_index=0,block_count=2,total_size=4096)
    if case=='wrong_total': raw=_b1_frame(0,b'a'*2048,block_index=0,block_count=2,total_size=4095)
    if case=='regressed': raw=_old_regions_frame(100,[(0,b'a'*4096)])+_old_regions_frame(99,[(0,b'a'*4096)])
    device._bridge=FakeBridge([raw]);device._bridge._ctx=SimpleNamespace(swd_clock_hz=30000000)
    if case=='stop':device._bridge._stop_stream_and_sync=Mock(return_value=False)
    clock(monkeypatch)
    response=client.post('/api/device/dump-memory/measure',json={'regions':[{'address':0,'size':4096}],'duration':1})
    assert response.status_code==500,response.text
    assert not state['resource_manager'].get_status()
    assert sum(c[0]=='enter' for c in device._bridge.calls)==1


def test_startup_allowance_and_partial_tail(monkeypatch):
    bridge=FakeBridge([b'',wire_samples(tail=True)])
    bridge._ctx=SimpleNamespace(swd_clock_hz=30000000)
    clock(monkeypatch,(0,.6,1.5,1.5,2.6))
    result=dump_benchmark.measure(SimpleNamespace(_bridge=bridge,_require_connected=lambda:None),[(0,4096)],duration=1)
    assert result['samples']==3 and result['incomplete_tail']
    assert bridge.calls[-1]==('exit',)


def test_gui_capture_is_not_preempted(batch):
    client,_,device,_,managers=batch
    managers['rtt'].running=True;device._bridge=Mock()
    response=client.post('/api/device/dump-memory/measure',json={'regions':[{'address':0,'size':4}]})
    assert response.status_code==409 and managers['rtt'].running
    device._bridge._enter_stream.assert_not_called()


def test_stop_requires_current_bridge_contract_without_delay_fallback():
    bridge=SimpleNamespace(_enter_stream=Mock(),_write_raw=Mock(),_exit_stream=Mock(),drain_stream_bytes=Mock())
    session=DumpMemoryStreamSession(bridge,[(0,4)],.001)
    session.start()
    with pytest.raises(AttributeError):session.stop()
    bridge._exit_stream.assert_not_called()
    bridge._write_raw.assert_called_once()
    assert not session.started


@pytest.mark.parametrize('failure',[False,True])
def test_cli_uses_shared_backend_and_detaches_without_replay(monkeypatch,failure):
    calls=[]
    class Client:
        def __init__(self,**kw):pass
        def connect(self,**kw):calls.append(('connect',kw))
        def call(self,name,args):
            calls.append((name,args))
            if failure:raise RuntimeErrorResponse('failed measurement')
            return {'samples':3}
        def close(self):calls.append(('detach',None))
    monkeypatch.setattr(runtime_cli,'RuntimeClient',Client)
    monkeypatch.setattr('mklink.device.connect',lambda **kw:pytest.fail('CLI opened CDC'))
    monkeypatch.setattr(sys,'argv',['mklink','dump-benchmark','0x20000000:4','--probe','chosen','--duration','.5'])
    if failure:
        with pytest.raises(SystemExit,match='failed measurement'):cli.main()
    else:cli.main()
    assert calls[0][1]['probe']=='chosen' and calls[0][1]['project_root'] is None
    assert calls[1]==('measure_dump_memory',{'regions':[{'address':0x20000000,'size':4}],'duration':.5,'period':.000001,'speed_profile':None})
    assert len(calls)==3 and calls[-1]==('detach',None)


def test_runtime_budget_covers_startup_and_stop(monkeypatch):
    call=Mock(return_value={});monkeypatch.setattr('mklink.runtime.request',call)
    client=RuntimeClient(info={});client.session_id='one'
    client.call('measure_dump_memory',{'regions':[{'address':0,'size':4}],'duration':30})
    call.assert_called_once()
    assert call.call_args.kwargs['timeout']==50


def test_mcp_measure_requires_connect_and_forwards_once(monkeypatch):
    calls=[]
    class ClientStub:
        info={}
        def __init__(self,**kw):calls.append('new')
        def connect(self,**kw):return {}
        def call(self,name,args):calls.append((name,args));return {'samples':3}
        def close(self):pass
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',ClientStub)
    body={'regions':[{'address':0,'size':4}]}
    async def run():
        async with Client(runtime_mcp.build_server()) as client:
            assert (await client.call_tool('measure_dump_memory',body,raise_on_error=False)).is_error
            assert not calls
            await client.call_tool('connect',{'probe':'chosen'})
            assert not (await client.call_tool('measure_dump_memory',body)).is_error
    asyncio.run(run())
    assert calls==['new',('measure_dump_memory',{**body,'duration':3.0,'period':.000001,'speed_profile':None})]
