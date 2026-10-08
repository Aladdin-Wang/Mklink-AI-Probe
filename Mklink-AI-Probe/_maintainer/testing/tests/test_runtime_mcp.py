"""Exercise the active shared MCP adapter, separately from legacy tool tests."""
import asyncio
import io
import subprocess
import sys

import pytest
from fastmcp import Client

from mklink import runtime_mcp
from test_shared_device import shared
from test_shared_runtime import runtime


def test_power_query_uses_selected_or_attached_backend_without_implicit_target(monkeypatch):
    created, queries = [], []
    class ProbeClient:
        info = {'port': 8765, 'token': 'existing'}
        def __init__(self, **options):
            created.append(options)
        def connect(self, **options):
            return {'attached': True}
        def close(self):
            pass
    def query(capability, **kwargs):
        queries.append((capability, kwargs))
        return {'voltage_mv': 3300}
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', ProbeClient)
    monkeypatch.setattr('mklink.runtime.query_probe', query)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            assert (await mcp.call_tool('get_power', {'probe': 'second'})).data['voltage_mv'] == 3300
            assert not created
            await mcp.call_tool('connect', {'probe': 'first'})
            await mcp.call_tool('get_power', {})
            await mcp.call_tool('get_power', {'probe': 'second'})
            await mcp.call_tool('get_power', {})
    asyncio.run(scenario())
    assert len(created) == 1
    assert queries == [('power_read', {'info': None, 'probe': 'second'}),
                       ('power_read', {'info': ProbeClient.info, 'probe': None}),
                       ('power_read', {'info': None, 'probe': 'second'}),
                       ('power_read', {'info': ProbeClient.info, 'probe': None})]


def test_tools_before_connect_do_not_create_implicit_client(monkeypatch):
    created = []
    class ProbeClient:
        info = None
        def __init__(self, **options):
            created.append(options)
        def call(self, *args):
            raise RuntimeError('Call connect first')
        def connect(self, **options):
            return {'attached': True}
        def close(self):
            pass
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', ProbeClient)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            for tool in ['device_status', 'read_memory', 'rtt_history', 'read_configuration']:
                args = ({'address': 0, 'size': 4} if tool == 'read_memory'
                        else {'part_number': 'HPM5301'} if tool == 'read_configuration' else {})
                assert (await mcp.call_tool(tool, args, raise_on_error=False)).is_error
            assert created == []
            await mcp.call_tool('connect', {'project_root': 'chosen-project', 'client_name': 'chosen-name'})
            assert created == [{'project_root': 'chosen-project', 'name': 'chosen-name'}]
    asyncio.run(scenario())


def test_configuration_read_mcp_obeys_shared_capture_gate_without_retry(shared):
    _, _, calls, managers, app = shared
    from fastapi import HTTPException
    @app.post('/api/device/configuration/read')
    async def read(body: dict):
        calls.append(body)
        raise HTTPException(422, 'unknown read result')
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'test'})
            managers['rtt'].running = True
            assert (await mcp.call_tool('read_configuration', {'part_number': 'HPM5301'}, raise_on_error=False)).is_error
            assert not calls and managers['rtt'].running
            assert (await mcp.call_tool('configuration_description', {'part_number': 'HPM5301'})).data['read_supported']
            managers['rtt'].running = False
            assert (await mcp.call_tool('read_configuration', {'part_number': 'HPM5301'}, raise_on_error=False)).is_error
    asyncio.run(scenario())
    assert calls == [{'part_number': 'HPM5301', 'model': 'V4'}]


@pytest.mark.parametrize('legacy', [False, True])
def test_peripheral_description_index_is_offline_and_registered_once(monkeypatch, legacy):
    from mklink import mcp_server
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline peripheral discovery connected hardware')
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',forbidden)
    monkeypatch.setattr(mcp_server,'_connected_device',forbidden)
    monkeypatch.setattr('mklink.peripheral_watch.list_svd_targets',lambda root,q:{'targets':[root,q]})
    server=mcp_server.build_server() if legacy else runtime_mcp.build_server()
    async def scenario():
        async with Client(server) as mcp:
            assert [tool.name for tool in await mcp.list_tools()].count('peripheral_targets')==1
            assert (await mcp.call_tool('peripheral_targets',{'project_root':'chosen','query':'GPIO'})).data=={'targets':['chosen','GPIO']}
    asyncio.run(scenario())


def test_peripheral_mcp_thin_adapters_use_explicit_shared_client(monkeypatch):
    calls=[]
    class Adapter:
        info=None
        def __init__(self,**kwargs): calls.append(('create',kwargs))
        def connect(self,**kwargs): return {'connected':True}
        def call(self,name,body):
            calls.append((name,body))
            return {'capability':name}
        def close(self): calls.append(('detach',None))
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',Adapter)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            for name,args in [('select_peripherals',{'chip':'TEST'}),('list_peripherals',{}),('capture_peripherals',{'names':['GPIOB.12']})]:
                assert (await mcp.call_tool(name,args,raise_on_error=False)).is_error
            assert not calls
            await mcp.call_tool('connect',{'probe':'selected'})
            await mcp.call_tool('select_peripherals',{'chip':'TEST'})
            await mcp.call_tool('list_peripherals',{'query':'GPIO'})
            await mcp.call_tool('capture_peripherals',{'names':['GPIOB.12'],'duration':.1})
            await mcp.call_tool('disconnect')
    asyncio.run(scenario())
    assert calls[1:]==[('select_peripherals',{'chip':'TEST'}),('list_peripherals',{'q':'GPIO'}),
                       ('capture_peripherals',{'names':['GPIOB.12'],'duration':.1,'period':.01}),('detach',None)]


@pytest.mark.parametrize('legacy', [False, True])
def test_offline_analysis_available_without_connect_and_preserves_trace_gaps(monkeypatch, legacy):
    from mklink import mcp_server
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline analysis attempted a device connection')
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', forbidden)
    monkeypatch.setattr(mcp_server, '_connected_device', forbidden)
    server = mcp_server.build_server() if legacy else runtime_mcp.build_server()
    async def scenario():
        async with Client(server) as mcp:
            names = [tool.name for tool in await mcp.list_tools()]
            assert names.count('systemview_decode') == names.count('systemview_analyze_events') == 1
            decoded = await mcp.call_tool('systemview_decode', {'hex_bytes': '11 01'})
            assert decoded.data['events'] == [{'kind': 'idle', 'delta_ticks': 1, 't_ticks': 1}]
            assert decoded.data['event_count'] == 1 and decoded.data['bytes_read'] == 2
            assert decoded.data['dropped_bytes'] == decoded.data['dropped_packets'] == 0
            invalid = await mcp.call_tool('systemview_decode', {'hex_bytes': '0x11'}, raise_on_error=False)
            assert invalid.is_error
            report = await mcp.call_tool('systemview_analyze_events', {'events': [
                {'kind': 'task_start_exec', 'task_id': 1, 't_us': 10},
                {'kind': 'overflow', 'drop_count': 1234, 't_us': 35000000},
                {'kind': 'task_start_exec', 'task_id': 2, 't_us': 35000100},
                {'kind': 'task_stop_exec', 'task_id': 2, 't_us': 35000300},
                {'kind': 'idle', 't_us': 35001100},
            ]})
            assert report.data['summary']['target_drop_count'] == 1234
            assert report.data['summary']['observed_us'] == 1000
            assert [task['id'] for task in report.data['tasks']] == [2]
            empty = await mcp.call_tool('systemview_analyze_events', {'events': []})
            assert empty.data['anomalies'][0]['kind'] == 'no_data'
    asyncio.run(scenario())


def test_mcp_debug_speed_uses_shared_admission_without_retry(shared):
    _, _, calls, managers, app = shared
    from fastapi import HTTPException
    @app.post('/api/device/debug-speed')
    async def speed(body: dict):
        calls.append(body)
        raise HTTPException(500, 'unknown clock result')
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'test'})
            managers['rtt'].running = True
            refused = await mcp.call_tool('set_debug_speed', {'profile': 'low'}, raise_on_error=False)
            assert refused.is_error and not calls and managers['rtt'].running
            # Offline tools remain available even while capture owns the bridge.
            assert not (await mcp.call_tool('systemview_decode', {'hex_bytes': '1101'})).is_error
            managers['rtt'].running = False
            failed = await mcp.call_tool('set_debug_speed', {'profile': 'low'}, raise_on_error=False)
            assert failed.is_error
    asyncio.run(scenario())
    assert calls == [{'profile': 'low'}]


def test_shared_stdio_does_not_import_legacy_device_server():
    result = subprocess.run([sys.executable, '-c', '''
import sys
import asyncio
from fastmcp import Client
from mklink import runtime_mcp
async def offline():
    async with Client(runtime_mcp.build_server()) as client:
        assert not (await client.call_tool('systemview_decode', {'hex_bytes': '1101'})).is_error
        assert not (await client.call_tool('systemview_analyze_events', {'events': []})).is_error
        assert not (await client.call_tool('configuration_description', {'part_number': 'HPM5301'})).is_error
asyncio.run(offline())
assert 'mklink.mcp_server' not in sys.modules
assert 'mklink.mcp_stream_bridge' not in sys.modules
class Server:
    def run(self, **kwargs):
        assert kwargs == {'transport': 'stdio', 'show_banner': False}
        assert 'mklink.mcp_server' not in sys.modules
        assert 'mklink.mcp_stream_bridge' not in sys.modules
runtime_mcp.build_server = Server
runtime_mcp.run()
assert 'mklink.mcp_server' not in sys.modules
'''], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_shared_stdio_restores_stdout_on_transport_error(monkeypatch):
    raw = io.BytesIO()
    protocol = io.TextIOWrapper(raw, encoding='utf-8')
    diagnostics = io.StringIO()
    class Server:
        def run(self, **kwargs):
            print('diagnostic')
            sys.stdout.buffer.write(b'{"jsonrpc":"2.0"}\n')
            sys.stdout.buffer.flush()
            raise RuntimeError('transport exit')
    monkeypatch.setattr(runtime_mcp, 'build_server', Server)
    monkeypatch.setattr(sys, 'stdout', protocol)
    monkeypatch.setattr(sys, 'stderr', diagnostics)
    with pytest.raises(RuntimeError, match='transport exit'):
        runtime_mcp.run()
    assert sys.stdout is protocol
    assert raw.getvalue() == b'{"jsonrpc":"2.0"}\n'
    assert diagnostics.getvalue() == 'diagnostic\n'


def test_mcp_lifespan_detaches_only_its_session_and_keeps_gui_capture(shared):
    http, control, calls, managers, _ = shared
    other = http.post('/_runtime/attach', json={'kind': 'sdk'}).json()['session_id']
    managers['rtt'].running = True
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'test'})
            assert len(control.sessions) == 2
            await mcp.call_tool('rtt_start')
            result = await mcp.call_tool('rtt_history')
            assert not result.is_error
            # Exit without the disconnect tool: the server lifecycle owns cleanup.
        assert list(control.sessions) == [other]
    asyncio.run(scenario())
    assert managers['rtt'].running and calls == []


def test_mcp_job_submission_uses_shared_session_and_can_query_after_disconnect(shared):
    _, control, calls, _, app = shared
    from fastapi import HTTPException
    @app.post('/api/device/reset')
    async def reset():
        calls.append('reset')
        raise HTTPException(500, 'unknown transport result')
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'test'})
            refused = await mcp.call_tool('start_job', {'action': 'reset', 'request_id': 'once'}, raise_on_error=False)
            assert refused.is_error and calls == []
            result = await mcp.call_tool('start_job', {'action': 'reset', 'request_id': 'once', 'confirm': True})
            job_id = result.data['job_id']
            for _ in range(100):
                status = await mcp.call_tool('job_status', {'job_id': job_id})
                if status.data['state'] != 'running':
                    break
                await asyncio.sleep(.01)
            assert status.data['state'] == 'unknown'
            duplicate = await mcp.call_tool('start_job', {'action': 'reset', 'request_id': 'once', 'confirm': True})
            assert duplicate.data['job_id'] == job_id
            await mcp.call_tool('disconnect')
            assert not control.sessions
            assert (await mcp.call_tool('job_status', {'job_id': job_id})).data['state'] == 'unknown'
        assert not control.sessions
    asyncio.run(scenario())
    assert calls == ['reset']


def test_mcp_inspects_catalog_without_attaching_hardware(monkeypatch):
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', lambda **kw: pytest.fail('Inspection attached hardware'))
    calls = []
    def inspect(**kwargs):
        calls.append(kwargs)
        return {'status': 'detected', 'device': 'TEST', 'profile_written': False}
    monkeypatch.setattr('mklink.mcu_detect.inspect_mcu', inspect)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            result = await mcp.call_tool('inspect_mcu', {'device': 'TEST', 'flm': 'algorithm'})
            assert result.data['status'] == 'detected'
    asyncio.run(scenario())
    assert calls == [{'project_root': '.', 'device': 'TEST', 'flm': 'algorithm'}]


@pytest.mark.parametrize('action', ['lock', 'unlock'])
def test_active_mcp_security_requires_explicit_confirmations_before_backend(monkeypatch, action):
    def forbidden(*a, **kw): pytest.fail('invalid request reached backend/client creation')
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', forbidden)
    monkeypatch.setattr('mklink.runtime.ensure_runtime', forbidden)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            status = await mcp.call_tool('security_status', {'target_part':'nrf54l15'})
            assert status.data['supported']
            body = {'target_part':'nrf54l15','request_id':'retained'}
            if action == 'lock': body['firmware']='app.bin'
            for update in ({}, {'confirm_user':'true'}, {'confirm_user':1},
                           {'confirm_user':True, 'voltage_mv':3300}):
                result = await mcp.call_tool('security_'+action, {**body,**update}, raise_on_error=False)
                assert result.is_error
            body['confirm_user']=True
            if action == 'unlock':
                for value in (False, 'true', 1):
                    assert (await mcp.call_tool('security_unlock',
                        {**body,'confirm_data_loss':value},raise_on_error=False)).is_error
            else:
                assert (await mcp.call_tool('security_lock',
                    {**body,'request_id':''},raise_on_error=False)).is_error
    asyncio.run(scenario())


def test_active_mcp_security_submits_without_target_and_can_query_after_disconnect(monkeypatch, tmp_path):
    calls = []
    info = {'probe_id':'usb-test'}
    def forbidden(*a, **kw): pytest.fail('security operation tried to attach a target')
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', forbidden)
    monkeypatch.setattr('mklink.runtime.ensure_runtime', lambda **kw: calls.append(('ensure',kw)) or info)
    job = {'job_id':'1'*32,'request_id':'known-id','state':'running','action':'security'}
    def request(endpoint, method, path, payload=None, **kw):
        assert endpoint is info
        calls.append((method,path,payload))
        return job
    monkeypatch.setattr('mklink.runtime.request', request)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            result = await mcp.call_tool('security_lock', dict(target_part='nrf54l15',
                firmware=str(tmp_path/'app.bin'),request_id='known-id',probe='alias',confirm_user=True))
            assert result.data['state']=='running'
            assert (await mcp.call_tool('disconnect')).data['detached']
            assert (await mcp.call_tool('job_status',{'job_id':'1'*32})).data['request_id']=='known-id'
    asyncio.run(scenario())
    assert calls[0] == ('ensure',{'project_root':'.','probe':'alias'})
    posts = [call for call in calls if call[0]=='POST']
    assert len(posts)==1 and posts[0][1]=='/api/runtime/jobs/'
    assert posts[0][2]['arguments']['action']=='lock'
    assert posts[0][2]['request_id']=='known-id'


def test_active_mcp_security_keeps_selection_after_lost_response(monkeypatch):
    calls=[]
    info={'probe_id':'usb-test'}
    monkeypatch.setattr('mklink.runtime.ensure_runtime',lambda **kw:info)
    def request(endpoint,method,path,payload=None,**kw):
        assert endpoint is info
        calls.append(method)
        if method=='POST': raise runtime_mcp.RuntimeErrorResponse('response lost')
        return {'jobs':[{'request_id':'lost-request','state':'running'}]}
    monkeypatch.setattr('mklink.runtime.request',request)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            result=await mcp.call_tool('security_unlock',dict(target_part='nrf54l15',
                request_id='lost-request',probe='usb-test',confirm_user=True,confirm_data_loss=True),raise_on_error=False)
            assert result.is_error and 'lost-request' in str(result)
            await mcp.call_tool('disconnect')
            assert (await mcp.call_tool('job_status')).data['jobs'][0]['request_id']=='lost-request'
    asyncio.run(scenario())
    assert calls==['POST','GET']


def test_attached_mcp_security_cannot_silently_switch_probes(monkeypatch):
    calls=[]
    class Attached:
        info={'probe_id':'first'}
        def __init__(self,**kw): pass
        def connect(self,**kw): return {'attached':True}
        def close(self): calls.append('detach')
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',Attached)
    monkeypatch.setattr('mklink.probes.select_probe',lambda selector:{'probe_id':selector})
    def forbidden(*a,**kw): pytest.fail('attached security must reuse endpoint')
    monkeypatch.setattr('mklink.runtime.ensure_runtime',forbidden)
    def request(info,method,path,payload=None,**kw):
        assert info is Attached.info
        calls.append('submit')
        return {'state':'running','request_id':payload['request_id']}
    monkeypatch.setattr('mklink.runtime.request',request)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect',{'probe':'first'})
            args=dict(target_part='nrf54l15',request_id='once',confirm_user=True,confirm_data_loss=True)
            assert (await mcp.call_tool('security_unlock',{**args,'probe':'second'},raise_on_error=False)).is_error
            assert calls==[]
            assert (await mcp.call_tool('security_unlock',args)).data['state']=='running'
            assert calls==['submit']
    asyncio.run(scenario())
    assert calls==['submit','detach']


def test_array_snapshot_mcp_actions_reuse_shared_gui_routes(monkeypatch):
    from mklink.runtime_capabilities import CAPABILITIES
    calls = []
    class Adapter:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): return {"connected": True}
        def close(self): pass
        def call(self, name, body):
            calls.append((name, body))
            return {"snapshot": body}
    monkeypatch.setattr(runtime_mcp, "RuntimeClient", Adapter)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool("connect", {})
            await mcp.call_tool("superwatch", {"action": "snapshot_select", "arguments": {"name": "samples", "start_index": 2, "count": 8}})
            await mcp.call_tool("superwatch", {"action": "snapshot_clear", "arguments": {}})
    asyncio.run(scenario())
    assert calls == [("superwatch_snapshot_select", {"name": "samples", "start_index": 2, "count": 8}), ("superwatch_snapshot_clear", {})]
    assert CAPABILITIES["superwatch_snapshot_select"] == ("POST", "/api/dash/superwatch/array-snapshot/select")
    assert CAPABILITIES["superwatch_snapshot_clear"] == ("POST", "/api/dash/superwatch/array-snapshot/clear")
