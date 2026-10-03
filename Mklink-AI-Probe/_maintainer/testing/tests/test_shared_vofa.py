import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import struct
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fastmcp import Client

from mklink import cli, runtime_cli, runtime_mcp
from mklink.dwarf_parser import DwarfInfo, DwarfVariable
from mklink.remote.dashboards import VofaStreamManager
from mklink.runtime import RuntimeErrorResponse
from mklink.symbol_catalog import SymbolCatalog
from mklink.vofa_viewer import parse_vofa_inputs, resolve_vofa_channels
from test_runtime_memory import batch
from test_shared_runtime import attach, call


@pytest.fixture
def vofa(batch, monkeypatch, tmp_path):
    client, state, device, control, managers = batch
    manager = VofaStreamManager(batch_samples=1)
    managers['vofa'] = manager
    device._bridge.current_mcu, device._bridge.idcode = 'fixture', 0
    axf = tmp_path / 'app.axf'
    axf.write_bytes(b'axf')
    info = DwarfInfo(base_types={1: ('uint32_t', 4)}, variables={
        'counter': DwarfVariable('counter', 10, 1, 0x20000000, 4, 'uint32_t')})
    device._axf, device._dwarf_info = str(axf), info
    device._symbol_catalog = SymbolCatalog.from_dwarf(info, axf_path=str(axf))
    behavior = SimpleNamespace(start_error=None, stop_error=None, read_error=None, empty=False, samples_left=None,
                               starts=[], stops=0, release=None, entered=threading.Event())
    class Session:
        stats = {}
        def __init__(self, bridge, pairs, period): self.pairs = pairs
        def start(self):
            behavior.entered.set()
            if behavior.release is not None:
                assert behavior.release.wait(5)
            if behavior.start_error: raise behavior.start_error
            behavior.starts.append(self.pairs)
        def read_frames(self, **kwargs):
            time.sleep(.001)
            if behavior.read_error: raise behavior.read_error
            if behavior.samples_left is not None:
                if behavior.samples_left <= 0: return []
                behavior.samples_left -= 1
            return [] if behavior.empty else [{'format': 'OLD', 'timestamp_us': 1, 'regions': [(i, bytes(size)) for i, (_, size) in enumerate(self.pairs)]}]
        def stop(self):
            behavior.stops += 1
            if behavior.stop_error: raise behavior.stop_error
    monkeypatch.setattr('mklink.dump_memory.DumpMemoryStreamSession', Session)
    yield client, state, device, control, managers, manager, behavior
    behavior.stop_error = None
    try: manager.stop()
    except RuntimeError: pass


def test_owner_subscriber_and_gui_use_one_producer(vofa):
    client, state, device, control, _, manager, behavior = vofa
    owner, peer = attach(client), attach(client)
    started = call(client, owner, 'vofa_start', {'channels': [{'path': 'counter'}], 'interval': .01})
    assert started.status_code == 200, started.text
    assert call(client, peer, 'vofa_start').json()['reused']
    assert call(client, peer, 'vofa_start', {'interval': .01}).status_code == 409
    for session in [owner, peer]:
        assert call(client, session, 'vofa_stop').status_code == 409
    assert client.post('/api/dash/vofa/stop').status_code == 409
    assert client.post('/api/dash/vofa/interval', json={'interval': .2}).status_code == 409
    assert call(client, peer, 'vofa_history').status_code == 200
    client.post('/_runtime/detach', json={'session_id': peer})
    assert manager.running and len(behavior.starts) == 1
    assert call(client, owner, 'vofa_stop').status_code == 200
    assert behavior.stops == 1 and not state['resource_manager'].get_status()
    assert not control.created_streams and not control.operation_lock.locked()
    device.read_memory.assert_not_called()


def test_gui_owned_capture_can_be_borrowed_but_not_stopped_by_ai(vofa):
    client, _, _, _, _, manager, behavior = vofa
    assert client.post('/api/dash/vofa/start', json={'channels': [{'path': 'counter'}]}).status_code == 200
    ai = attach(client)
    assert call(client, ai, 'vofa_start').json()['reused']
    assert call(client, ai, 'vofa_stop').status_code == 409
    client.post('/_runtime/detach', json={'session_id': ai})
    assert manager.running and behavior.stops == 0
    assert client.post('/api/dash/vofa/stop').status_code == 200


def test_vofa_does_not_preempt_gui_rtt(vofa):
    client, state, _, _, managers, _, behavior = vofa
    managers['rtt'].running = True
    response = call(client, attach(client), 'vofa_start', {'channels': [{'path': 'counter'}]})
    assert response.status_code == 409
    assert not behavior.starts and managers['rtt'].running and not state['resource_manager'].get_status()


@pytest.mark.parametrize('channels', [[], [{'path': 'missing'}], [{'path': 'counter', 'type': 'float'}],
    [{'addr': True}], [{'addr': 1.5}], [{'addr': 0, 'size': True}], [{'addr': 0, 'name': False}],
    [{'addr': 0, 'size': '4'}], [{'path': 'counter', 'addr': 0}],
    [{'addr': 0x20000000+i*4096} for i in range(16)]])
def test_invalid_vofa_never_starts_or_leases(vofa, channels):
    client, state, device, _, _, _, behavior = vofa
    response = client.post('/api/dash/vofa/start', json={'channels': channels})
    assert response.status_code in (400, 422), response.text
    assert not behavior.starts and not state['resource_manager'].get_status()
    device.read_memory.assert_not_called()


def test_cached_symbolic_channels_resolve_again_after_catalog_change(vofa):
    client, _, device, _, _, manager, behavior = vofa
    body = {'channels': [{'path': 'counter'}]}
    assert client.post('/api/dash/vofa/start', json=body).status_code == 200
    assert client.post('/api/dash/vofa/stop').status_code == 200
    catalog = device.symbol_catalog
    descriptor = replace(catalog.items[0], address=0x20000004)
    device._symbol_catalog = replace(catalog, generation=catalog.generation+1, items=(descriptor,))
    assert client.post('/api/dash/vofa/start', json={}).status_code == 200
    assert behavior.starts == [[(0x20000000, 4)], [(0x20000004, 4)]]
    assert manager.get_status()['channels'][0]['addr'] == 0x20000004


def test_stale_source_blocks_vofa_without_reloading(vofa):
    from pathlib import Path
    client, state, device, _, _, _, behavior = vofa
    catalog = device.symbol_catalog
    Path(catalog.axf_path).write_bytes(b'new')
    response = client.post('/api/dash/vofa/start', json={'channels': [{'path': 'counter'}]})
    assert response.status_code == 409, response.text
    assert not behavior.starts and not state['resource_manager'].get_status()
    assert device.symbol_catalog is catalog


def test_start_failure_reaches_client_and_releases_lease(vofa):
    client, state, _, control, _, manager, behavior = vofa
    behavior.start_error = OSError('write failed')
    response = call(client, attach(client), 'vofa_start', {'channels': [{'path': 'counter'}]})
    assert response.status_code == 500 and 'write failed' in response.text
    assert not state['resource_manager'].get_status() and not control.operation_lock.locked()
    assert not control.created_streams and manager.get_status()['error'] == 'write failed'


def test_slow_start_keeps_gate_and_does_not_claim_running_early(vofa):
    client, state, _, control, _, _, behavior = vofa
    behavior.release = threading.Event()
    session = attach(client)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(call, client, session, 'vofa_start', {'channels': [{'path': 'counter'}]})
        assert behavior.entered.wait(5)
        try:
            assert not pending.done() and control.operation_lock.locked()
            assert state['resource_manager'].get_status()
            assert call(client, session, 'vofa_start').status_code == 409
        finally: behavior.release.set()
        assert pending.result(timeout=5).status_code == 200
    assert len(behavior.starts) == 1


def test_failed_stop_is_not_reported_as_success_or_replayed(vofa):
    client, state, _, _, _, manager, behavior = vofa
    session = attach(client)
    assert call(client, session, 'vofa_start', {'channels': [{'path': 'counter'}]}).status_code == 200
    behavior.stop_error = TimeoutError('stop unconfirmed')
    response = call(client, session, 'vofa_stop')
    assert response.status_code == 500 and 'stop unconfirmed' in response.text
    assert behavior.stops == 1 and not manager.running
    assert manager.get_status()['error'] == 'stop unconfirmed'
    assert not state['resource_manager'].get_status()


def test_terminal_read_failure_is_visible_and_releases_resource(vofa):
    client, state, _, _, _, manager, behavior = vofa
    assert client.post('/api/dash/vofa/start', json={'channels': [{'path': 'counter'}]}).status_code == 200
    behavior.read_error = OSError('device lost')
    manager._thread.join(2)
    assert not manager._thread.is_alive() and not manager.running
    history = client.get('/api/dash/vofa/history').json()
    assert history['error'] == 'device lost' and not state['resource_manager'].get_status()
    assert behavior.stops == 1


def test_cli_inputs_preserve_contiguous_float_and_typed_or_catalog_paths():
    assert len(parse_vofa_inputs(['0x20000000', '16'])) == 16
    assert parse_vofa_inputs(['samples', '2']) == [{'path': 'samples[0]', 'type': 'float'}, {'path': 'samples[1]', 'type': 'float'}]
    assert parse_vofa_inputs(['counter', 'uint32_t'], 'count') == [{'path': 'counter', 'type': 'uint32_t', 'name': 'count'}]
    assert parse_vofa_inputs(['counter']) == [{'path': 'counter'}]


@pytest.mark.parametrize('arguments', [['--period', 'nan'], ['--period','-1'], ['--period','0'],
    ['--period','61'], ['--stop'], ['0xfffffffc','2'], ['counter','--names','a,b'],
    ['0x20000000);reset()','float'], ['--names','a']])
def test_bad_cli_input_never_connects(monkeypatch, arguments):
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', lambda **kw: pytest.fail('opened backend'))
    monkeypatch.setattr(sys, 'argv', ['mklink','vofa',*arguments])
    with pytest.raises(SystemExit) as error: cli.main()
    assert error.value.code


@pytest.mark.parametrize('borrowed,stop_error,terminal_error', [
    (True,None,None),(False,None,None),(False,409,None),(False,500,None),(False,None,'device lost')])
def test_cli_ownership_and_failure_exit(monkeypatch, borrowed, stop_error, terminal_error):
    calls=[]
    class Adapter:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): calls.append(('connect',kwargs))
        def call(self, name, arguments=None):
            calls.append((name,arguments))
            if name == 'vofa_status':
                error = terminal_error if sum(n=='vofa_status' for n,_ in calls)>1 else None
                return {'running':borrowed or any(n=='vofa_start' for n,_ in calls), 'error':error}
            if name == 'vofa_start': return {'reused':borrowed}
            if name == 'vofa_stop' and stop_error: raise RuntimeErrorResponse('stop rejected', status_code=stop_error)
            if name == 'vofa_history': return {'points':[{'counter':1}], 'completed_samples':1}
            return {}
        def close(self): calls.append(('detach',None))
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', Adapter)
    arguments=['mklink','vofa','--probe','chosen','--duration','.001']
    if not borrowed: arguments.append('counter')
    monkeypatch.setattr(sys,'argv',arguments)
    if terminal_error or stop_error==500:
        with pytest.raises(SystemExit): cli.main()
    else: cli.main()
    assert calls[0][1]['project_root'] is None and calls[0][1]['probe']=='chosen'
    assert calls[-1][0]=='detach'
    assert sum(name=='vofa_stop' for name,_ in calls)==int(not borrowed)
    assert ('vofa_start',{}) in calls if borrowed else ('vofa_start',{'interval':.001,'channels':[{'path':'counter'}]}) in calls


def test_mcp_vofa_uses_generic_capability_without_private_transport(monkeypatch):
    calls=[]
    class Adapter:
        info={}
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): return {}
        def call(self, name, arguments): calls.append((name,arguments)); return {}
        def close(self): pass
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',Adapter)
    async def run():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe':'chosen'})
            await mcp.call_tool('gui_call', {'capability':'vofa_start','arguments':{}})
            await mcp.call_tool('gui_call', {'capability':'vofa_history','arguments':{}})
    asyncio.run(run())
    assert calls==[('vofa_start',{}),('vofa_history',{})]


def test_visualizer_url_selects_only_known_shared_pages():
    from mklink.runtime import browser_url
    info = {'port': 12345, 'token': 'secret'}
    assert browser_url(info, page='vofa') == 'http://127.0.0.1:12345/_runtime/open?page=vofa#secret'
    assert browser_url(info).endswith('/_runtime/open#secret')
    with pytest.raises(ValueError):
        browser_url(info, page='https://external.invalid/')


@pytest.mark.parametrize('option', ['--stop', '--host', '--port-http', '--max-points'])
def test_removed_private_vofa_server_options_fail_before_connect(monkeypatch, option):
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', lambda **kw: pytest.fail('unexpected connection'))
    monkeypatch.setattr(sys, 'argv', ['mklink', 'vofa', option])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


@pytest.mark.parametrize('name', ['_t', '_seq', 'event', '_event'])
def test_vofa_labels_cannot_overwrite_sample_metadata(name):
    with pytest.raises(ValueError, match='reserved'):
        parse_vofa_inputs(['0x20000000', 'uint32_t'], name)


@pytest.mark.parametrize('regions', [[(0, bytes(4)), (0, bytes(4))], [(0, bytes(4)), (1, bytes(4))]])
def test_vofa_reuses_strict_region_validation_even_while_paused(regions):
    manager = VofaStreamManager(batch_samples=1)
    manager.configure([{'addr': 0x20000000, 'type': 'uint32_t'}])
    manager.pause()
    assert manager._accept_dump_frame({'format': 'OLD', 'timestamp_us': 1, 'regions': regions}) is False
    assert manager.get_status()['read_errors'] == 1 and manager.get_history() == []


def test_vofa_assembles_b1_blocks_before_publishing():
    manager = VofaStreamManager(batch_samples=1)
    manager.configure([{'addr': 0x20000000, 'type': 'uint32_t'}])
    base = dict(format='B1', timestamp_us=1, total_size=4, block_size=2, block_count=2, block_crc_ok=True)
    assert manager._accept_dump_frame(dict(base, block_index=0, regions=[(0, bytes([42, 0]))])) is None
    assert manager.get_history() == []
    assert manager._accept_dump_frame(dict(base, block_index=1, regions=[(0, bytes(2))])) is True
    assert manager.get_history()[0]['0x20000000'] == 42


def test_sparse_samples_reach_waveform_before_batch_fills(vofa):
    from mklink.remote.stream_hub import StreamHub
    client, _, _, _, _, manager, behavior = vofa
    hub = StreamHub(max_batches_per_client=4)
    manager.set_stream_hub(hub)
    manager._batch_samples = 32
    behavior.samples_left = 1
    assert client.post('/api/dash/vofa/start', json={'channels': [{'path': 'counter'}], 'interval': .5}).status_code == 200
    deadline = time.monotonic() + 1
    while hub.stats().produced_items == 0 and time.monotonic() < deadline:
        time.sleep(.005)
    assert manager.running and hub.stats().produced_items == 1
    assert client.post('/api/dash/vofa/stop').status_code == 200
