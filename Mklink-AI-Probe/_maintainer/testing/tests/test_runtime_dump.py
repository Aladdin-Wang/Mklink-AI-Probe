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
    assert [sample['timestamp_us'] for sample in result['samples']]==[1,3]
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


@pytest.mark.parametrize('byte_limit_delta', [0, -1])
def test_packed_capture_keeps_payloads_timestamps_and_exact_json_limit(monkeypatch, byte_limit_delta):
    import json
    from types import SimpleNamespace
    from mklink.mux_watch import PackedWatchSample
    expected = [{'sample_index': 0, 'timestamp_us': 2**32 + 12, 'regions': [
        {'address': '0x20000000', 'size': 4, 'data_hex': '0001feff'},
        {'address': '0x20000010', 'size': 4, 'data_hex': '10203040'}]}]
    session = Mock()
    session.parser.crc_errors = 0
    session.stats = {'parser_dropped_bytes': 0}
    session.read_frames.return_value = [PackedWatchSample(2**32 + 12,
        bytes.fromhex('aabb0001feff10203040'), 2)]
    monkeypatch.setattr(dump_memory, 'DumpMemoryStreamSession', lambda *a, **k: session)
    exact = len(json.dumps(expected[0], separators=(',', ':')).encode()) + 1
    monkeypatch.setattr(dump_memory, 'MAX_DUMP_RESULT_JSON_BYTES', exact + byte_limit_delta)
    def capture():
        return dump_memory.capture_dump_stream(SimpleNamespace(_bridge=None),
            [{'address': 0x20000000, 'size': 4}, {'address': 0x20000010, 'size': 4}],
            period=.000001, frames=1)
    if byte_limit_delta:
        with pytest.raises(ValueError, match='16 MiB'): capture()
    else:
        result = capture()
        assert result['samples'] == expected
        assert not result['incomplete_tail']
    assert session.packed_frames is True
    session.stop.assert_called_once()


def test_periodic_capture_rejects_queue_loss_after_confirmed_stop(monkeypatch):
    from types import SimpleNamespace
    from mklink.mux_watch import PackedWatchSample
    session = Mock()
    session.parser.crc_errors = 0
    session.stats = {'parser_dropped_bytes': 1024}
    session.read_frames.return_value = [PackedWatchSample(1, b'abcd', 0)]
    monkeypatch.setattr(dump_memory, 'DumpMemoryStreamSession', lambda *a, **k: session)
    with pytest.raises(RuntimeError, match='integrity failure'):
        dump_memory.capture_dump_stream(SimpleNamespace(_bridge=None),
            [{'address': 0x20000000, 'size': 4}], period=.000001, frames=1)
    session.stop.assert_called_once()


@pytest.mark.parametrize('before_start', [False, True])
def test_capture_session_cancel_stops_without_returning_partial_result(before_start):
    from types import SimpleNamespace
    bridge = FakeBridge([_b1_frame(1,b'A'*2048,block_index=0,block_count=2,total_size=4096)])
    checks = 0
    def cancelled():
        nonlocal checks
        checks += 1
        return before_start or checks >= 4
    with pytest.raises(InterruptedError, match='owning session ended'):
        dump_memory.capture_dump_stream(SimpleNamespace(_bridge=bridge), [{'address':0,'size':4096}],
                                        period=.01, frames=0, duration=8, cancelled=cancelled)
    if before_start:
        assert not bridge.calls
    else:
        assert bridge.calls[-1] == ('exit',)
        assert bridge.calls.count(('write', b'cmd.dump_memory(0x00000000, 4096, 0.01)\n')) == 1


def test_capture_owner_lease_check_ignores_other_clients():
    from types import SimpleNamespace
    import time
    from mklink.runtime_api import active_operation, operation_session_ended
    owner=SimpleNamespace(expires=time.monotonic()+10)
    control=SimpleNamespace(sessions={'owner':owner})
    token=active_operation.set((control,'owner'))
    try:
        assert not operation_session_ended()
        owner.expires=time.monotonic()-1
        control.sessions['other']=SimpleNamespace(expires=time.monotonic()+10)
        assert operation_session_ended()
        owner.expires=time.monotonic()+10
        assert not operation_session_ended()
        del control.sessions['owner']
        assert operation_session_ended()
    finally:
        active_operation.reset(token)
    assert not operation_session_ended()


def test_cancel_does_not_hide_failed_stop_confirmation():
    from types import SimpleNamespace
    bridge = FakeBridge([])
    bridge._stop_stream_and_sync = Mock(return_value=False)
    checks = iter([False, True])
    with pytest.raises(TimeoutError, match='stop'):
        dump_memory.capture_dump_stream(SimpleNamespace(_bridge=bridge), [{'address':0,'size':4096}],
                                        period=.01, frames=0, duration=8, cancelled=lambda: next(checks))
    bridge._stop_stream_and_sync.assert_called_once()


@pytest.mark.parametrize('path,implementation', [
    ('','mklink.dump_memory.capture_memory'),
    ('capture','mklink.dump_memory.capture_dump_stream'),
    ('measure','mklink.dump_benchmark.measure'),
])
def test_disconnected_capture_holds_admission_until_worker_cleanup(batch, monkeypatch, path, implementation):
    import time
    from starlette.requests import Request
    client,state,device,control,_=batch
    entered,disconnect,cleaning,release=(threading.Event() for _ in range(4))
    async def receive_disconnect():
        while not disconnect.is_set():
            await asyncio.sleep(.005)
        return {'type':'http.disconnect'}
    monkeypatch.setattr(Request,'receive',property(lambda self: receive_disconnect))
    def worker(*args,cancelled,**kwargs):
        entered.set()
        deadline=time.monotonic()+5
        while not cancelled():
            assert time.monotonic()<deadline
            time.sleep(.005)
        cleaning.set()
        assert release.wait(5)
        raise InterruptedError('cancelled after cleanup')
    monkeypatch.setattr(implementation,worker)
    with ThreadPoolExecutor() as pool:
        result=pool.submit(client.post,'/api/device/dump-memory'+('/'+path if path else ''),
                           json={'regions':[{'address':0,'size':4}]})
        assert entered.wait(5)
        try:
            disconnect.set()
            assert cleaning.wait(5)
            assert control.operation_lock.locked()
            assert state['resource_manager'].get_status()
            assert client.post('/api/dash/rtt/start',json={}).status_code==409
        finally:
            release.set()
        response=result.result(timeout=5)
    assert response.status_code==500 and 'cancelled after cleanup' in response.text
    assert not control.operation_lock.locked()
    assert not state['resource_manager'].get_status()


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

@pytest.mark.parametrize('failure', [None, 'active sampling', 'exit response lost'])
def test_legacy_snapshot_leaves_mux_before_claiming_or_writing(failure):
    bridge=FakeBridge([_old_regions_frame(1,[(0,b'abcd')])])
    events=[]
    original_enter=bridge._enter_stream
    original_write=bridge._write_raw
    def leave():
        events.append('leave_mux')
        if failure:raise RuntimeError(failure)
    bridge._leave_multiplex=leave
    def enter(state):
        events.append('claim_legacy')
        original_enter(state)
    def write(data):
        events.append('write')
        original_write(data)
    bridge._enter_stream=enter
    bridge._write_raw=write
    if failure:
        with pytest.raises(RuntimeError,match=failure):
            dump_memory.read_dump_memory_regions_once(bridge,[(0,4)])
        assert events==['leave_mux']
    else:
        assert dump_memory.read_dump_memory_regions_once(bridge,[(0,4)])==(b'abcd',)
        assert events[:3]==['leave_mux','claim_legacy','write']

@pytest.mark.parametrize('before_start,stop_fails', [(True,False),(False,False),(False,True)])
def test_snapshot_cancel_during_partial_frame_confirms_stop(before_start,stop_fails):
    from types import SimpleNamespace
    bridge=FakeBridge([_b1_frame(1,b'A'*2048,block_index=0,block_count=2,total_size=4096)])
    if stop_fails:
        bridge._stop_stream_and_sync=Mock(side_effect=TimeoutError('stop unconfirmed'))
    checks=0
    def cancelled():
        nonlocal checks
        checks+=1
        return before_start or checks>=6
    with pytest.raises(TimeoutError if stop_fails else InterruptedError):
        dump_memory.capture_memory(SimpleNamespace(_bridge=bridge),[{'address':0,'size':4096}],sample_count=4,cancelled=cancelled)
    if before_start:
        assert not bridge.calls
    elif stop_fails:
        bridge._stop_stream_and_sync.assert_called_once()
    else:
        assert bridge.calls[-1]==('exit',)
        assert bridge.calls.count(('write',b'cmd.dump_memory(0x00000000, 4096, 0)\n'))==1


def test_snapshot_cancel_between_samples_does_not_issue_next_read():
    from types import SimpleNamespace
    bridge=FakeBridge([_old_regions_frame(1,[(0,b'ABCD')])])
    ended=False
    def published(*args):
        nonlocal ended
        ended=True
        return True
    with pytest.raises(InterruptedError):
        dump_memory.capture_memory(SimpleNamespace(_bridge=bridge),[{'address':0,'size':4}],sample_count=2,
                                   publish_sample=published,cancelled=lambda:ended)
    assert bridge.calls.count(('write',b'cmd.dump_memory(0x00000000, 4, 0)\n'))==1
    assert bridge.calls[-1]==('exit',)
