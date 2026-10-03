import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mklink.remote import debug_api
from mklink import debug_control as debug
from test_shared_runtime import runtime, attach, call


@pytest.fixture
def device(monkeypatch):
    monkeypatch.setattr('mklink.peripheral_watch.load_catalog',lambda root:None)
    return SimpleNamespace(connected=True, _project_root='.', _axf=None, _elf_backend=None,
                           _require_cortex_m_debug=Mock(), read_memory=Mock(return_value=bytes(4)),
                           read_register=Mock(return_value=42), halt=Mock())


@pytest.mark.parametrize('body', [
    {'address':'0xfffffffc','count':2}, {'address':True}, {'address':'0x20000001'},
    {'register':'SCB.CPUID','address':'0'}, {'address':'0','count':True},
    {'address':'0','count':1025}, {'address':'0','width':8}, {'address':'0','extra':True},
])
def test_invalid_register_snapshot_never_reads(device,body):
    with pytest.raises((ValueError,KeyError)):debug_api.register_snapshot(device,body)
    device.read_memory.assert_not_called()
    device.read_register.assert_not_called()


def test_register_batch_and_short_read(device):
    device.read_memory.return_value=(7).to_bytes(4,'little')
    result=debug_api.register_snapshot(device,{'register':'SCB.CPUID','count':2})
    assert result['values']==[42,7]
    device.read_memory.assert_called_once_with(0xe000ed04,4)
    with pytest.raises(RuntimeError,match='Incomplete'):
        debug_api.register_snapshot(device,{'address':'0','count':2})


def test_catalog_exclusions_and_field_decoding_remain_authoritative(device,monkeypatch):
    item=SimpleNamespace(name='GPIO.FIELD',address=0x40000000)
    catalog=SimpleNamespace(resolve=Mock(return_value=item))
    monkeypatch.setattr('mklink.peripheral_watch.load_catalog',lambda root:catalog)
    reader=Mock(return_value=3)
    monkeypatch.setattr('mklink.peripheral_watch.read_item',reader)
    assert debug_api.register_snapshot(device,{'register':'GPIO.FIELD'})['values']==[3]
    reader.assert_called_once_with(device,item)
    for body in ({'address':'0'}, {'register':'GPIO.FIELD','raw':True}, {'register':'GPIO.FIELD','count':2}):
        with pytest.raises(ValueError):debug_api.register_snapshot(device,body)
    catalog.resolve.side_effect=ValueError('excluded register')
    with pytest.raises(ValueError,match='excluded'):debug_api.register_snapshot(device,{'register':'GPIO.BAD'})
    device.read_memory.assert_not_called()


def test_fault_snapshot_reads_architectural_registers_without_halting(device):
    device.read_memory.side_effect=lambda addr,size: bytes(size)
    result=debug_api.fault_snapshot(device,{'sp':'0x20000000'})
    assert len(result['registers'])==5 and len(result['frame'])==8
    assert result['halt_requested'] is False
    device.halt.assert_not_called()
    device.read_register.assert_not_called()
    assert device.read_memory.call_args_list[-1].args==(0x20000000,32)


@pytest.mark.parametrize('body',[{'sp':'0xfffffff0'},{'sp':True},{'sp':'0x20000001'},{'pause':True}])
def test_fault_validation_before_reads(device,body):
    with pytest.raises(ValueError):debug_api.fault_snapshot(device,body)
    device.read_memory.assert_not_called()


def test_fault_short_read_is_error_not_no_fault(device):
    device.read_memory.return_value=b''
    with pytest.raises(RuntimeError,match='Incomplete'):debug_api.fault_snapshot(device,{})


@pytest.fixture
def fpb(device,monkeypatch):
    memory={debug.FP_CTRL:0x60,debug.DHCSR:0}
    reads=[];writes=[]
    def read(bridge,addr):reads.append(addr);return memory.get(addr,0)
    def write(bridge,addr,value):
        writes.append((addr,value))
        memory[addr]=(memory[addr] & ~3) | (value & 1) if addr==debug.FP_CTRL else value
    monkeypatch.setattr(debug,'_read_u32',read)
    monkeypatch.setattr(debug,'_write_u32',write)
    device._bridge=object()
    device.set_breakpoint=lambda addr,slot:debug.set_breakpoint(device._bridge,addr,slot)
    device.clear_breakpoint=lambda slot:debug.clear_breakpoint(device._bridge,slot)
    return device,memory,reads,writes


@pytest.mark.parametrize('body',[
    {'action':'clear','slot':-1},{'action':'clear','slot':True},{'action':'clear','slot':6},
    {'action':'set','target':'0x20000000'}, {'action':'set','target':'0x08005001'},
    {'action':'set','target':'0x08005000','slot':6}, {'action':'clear_all','slot':0},
    {'action':'status','target':'main'}, {'action':'set'}, {'action':'unknown'},
])
def test_bad_breakpoint_never_writes(fpb,body):
    device,memory,reads,writes=fpb
    with pytest.raises(ValueError):debug_api.breakpoints(device,body)
    assert writes==[]


def test_breakpoint_preserves_occupied_slots_and_decodes_upper_halfword(fpb):
    device,memory,reads,writes=fpb
    memory[debug.FP_COMP_BASE]=0x48005001
    with pytest.raises(ValueError,match='free'):
        debug_api.breakpoints(device,{'action':'set','target':'0x08005002','slot':0})
    assert writes==[]
    result=debug_api.breakpoints(device,{'action':'set','target':'0x08005002'})
    assert result['slot']==1 and result['verified']
    state=debug_api.breakpoints(device,{'action':'status'})
    assert state['breakpoints'][1]['address']==0x08005002
    debug_api.breakpoints(device,{'action':'clear','slot':1})
    assert memory[debug.FP_COMP_BASE]==0x48005001
    assert memory[debug.FP_COMP_BASE+4]==0


def test_unsupported_revision_and_full_slots_never_write(fpb):
    device,memory,reads,writes=fpb
    memory[debug.FP_CTRL]=0x10000060
    with pytest.raises(ValueError,match='FPBv1'):debug_api.breakpoints(device,{'action':'clear_all'})
    memory[debug.FP_CTRL]=0x60
    for i in range(6):memory[debug.FP_COMP_BASE+4*i]=0x48005001
    with pytest.raises(ValueError,match='free'):debug_api.breakpoints(device,{'action':'set','target':'0x08005000'})
    assert writes==[]


def test_function_uses_backend_symbols_and_normalizes_thumb_bit(fpb,monkeypatch):
    device,memory,reads,writes=fpb
    device._axf='shared.axf'
    resolver=Mock(return_value=0x08005003)
    monkeypatch.setattr(debug,'resolve_function_address',resolver)
    assert debug_api.breakpoints(device,{'action':'set','target':'function'})['address']==0x08005002
    resolver.assert_called_once_with('shared.axf','function',backend=None,project_root='.')


def test_failed_breakpoint_write_not_retried(fpb,monkeypatch):
    device,memory,reads,writes=fpb
    writer=Mock()
    monkeypatch.setattr(debug,'_write_u32',writer)
    with pytest.raises(RuntimeError,match='verification'):
        debug_api.breakpoints(device,{'action':'set','target':'0x08005000'})
    assert writer.call_count==2  # enable once + comparator once; no retries


@pytest.mark.parametrize('capability',['register_snapshot','fault_snapshot','breakpoints'])
def test_shared_gate_rejects_during_capture_and_job(runtime,capability):
    client,control,calls,managers,app=runtime
    session=attach(client)
    managers['rtt'].running=True
    assert call(client,session,capability).status_code==409
    managers['rtt'].running=False
    control.job_busy=lambda:True
    assert call(client,session,capability).status_code==409
    assert calls==[]


def test_worker_holds_single_lease_without_blocking_loop(device):
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from route_utils import find_route
    entered,release=threading.Event(),threading.Event()
    events=[]
    @asynccontextmanager
    async def lease(state,operation):
        events.append('acquire')
        try:yield
        finally:events.append('release')
    def read(addr,size):
        entered.set();release.wait(3)
        assert events==['acquire']
        return bytes(size)
    device.read_memory.side_effect=read
    app=FastAPI();app.include_router(debug_api.create_debug_router({'device':device},lease))
    async def scenario():
        task=asyncio.create_task(find_route(app,'/api/device/fault-snapshot').endpoint({}))
        try:
            assert await asyncio.to_thread(entered.wait,2)
            assert not task.done()
        finally:
            release.set();await task
        assert events==['acquire','release']
    asyncio.run(scenario())
