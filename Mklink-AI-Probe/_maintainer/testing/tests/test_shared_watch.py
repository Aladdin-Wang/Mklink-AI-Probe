"""Watch uses one current catalog and the real shared gate/batch reader."""
import asyncio
import json
import os
import struct
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastmcp import Client

from mklink import SharedDevice, cli, runtime_cli, runtime_mcp
from mklink.dwarf_parser import DwarfInfo, DwarfVariable
from mklink.runtime import RuntimeErrorResponse
from mklink.symbol_catalog import SymbolCatalog
from mklink.watch import MapSourceSnapshot
from test_runtime_memory import batch
from test_shared_runtime import attach, call


@pytest.fixture
def watch(batch, tmp_path):
    client, state, device, control, managers = batch
    axf = tmp_path / 'app.axf'
    axf.write_bytes(b'catalog')
    info = DwarfInfo(base_types={1: ('uint32_t', 4)}, variables={
        'a': DwarfVariable('a', 3, 1, 0x20000000, 4, 'uint32_t'),
        'b': DwarfVariable('b', 4, 1, 0x20000004, 4, 'uint32_t'),
        'constant': DwarfVariable('constant', 5, 1, 0x08005000, 4, 'uint32_t')})
    device._axf, device._dwarf_info = str(axf), info
    device._bridge.current_mcu = 'fixture'
    device._bridge.idcode = 0
    device._symbol_catalog = SymbolCatalog.from_dwarf(info, axf_path=str(axf))
    return batch


def test_watch_batches_current_catalog_reads_in_input_order(watch):
    client, state, device, control, _ = watch
    first, second = attach(client), attach(client)
    response = call(client, first, 'watch', {'names': ['b', 'a', 'constant']})
    assert response.status_code == 200, response.text
    assert [row['name'] for row in response.json()['rows']] == ['b', 'a', 'constant']
    assert [row['value'] for row in response.json()['rows']] == [0x07060504, 0x03020100, 0x03020100]
    assert sorted(row.args for row in device.read_memory.call_args_list) == [(0x08005000, 4), (0x20000000, 8)]
    assert len(control.sessions) == 2 and not state['resource_manager'].get_status()
    client.post('/_runtime/detach', json={'session_id': first})
    assert call(client, second, 'watch', {'names': ['a']}).status_code == 200
    device.close.assert_not_called()


@pytest.mark.parametrize('names', [None, [], 'a', [None], [True], [''], ['a', ' a '],
                                  ['x'*257], ['a']*17, ['a', 'missing'], ['a', 'constant.field']])
def test_invalid_or_unresolved_watch_does_no_io(watch, names):
    client, state, device, _, _ = watch
    response = client.post('/api/device/watch', json={'names': names})
    assert response.status_code == 422, response.text
    device.read_memory.assert_not_called()
    assert not state['resource_manager'].get_status()


def test_watch_conflict_does_not_preempt_gui_and_releases_only_own_lease(watch):
    client, state, device, control, managers = watch
    session = attach(client)
    managers['rtt'].running = True
    assert call(client, session, 'watch', {'names': ['a']}).status_code == 409
    assert managers['rtt'].running and len(control.sessions) == 1
    device.read_memory.assert_not_called()
    managers['rtt'].running = False
    assert call(client, session, 'watch', {'names': ['a']}).status_code == 200
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('failure', [b'', TimeoutError('lost response')])
def test_watch_failure_is_not_retried_or_returned_as_partial_success(watch, failure):
    client, state, device, _, _ = watch
    device.read_memory.side_effect = failure if isinstance(failure, Exception) else lambda *a: failure
    assert client.post('/api/device/watch', json={'names': ['a', 'constant']}).status_code == 500
    assert device.read_memory.call_count == 1 and not state['resource_manager'].get_status()


@pytest.mark.parametrize('during_read', [False, True])
def test_watch_changed_axf_conflicts_without_reparse(watch, during_read):
    from pathlib import Path
    client, _, device, control, _ = watch
    session = attach(client)
    catalog = device.symbol_catalog
    def change(*args):
        path = Path(catalog.axf_path)
        timestamp = path.stat().st_mtime_ns
        path.write_bytes(b'changed')
        os.utime(path, ns=(timestamp, timestamp))
        return bytes(4)
    if during_read:
        device.read_memory.side_effect = change
    else:
        change()
    response = call(client, session, 'watch', {'names': ['a']})
    assert response.status_code == 409, response.text
    assert device.read_memory.call_count == int(during_read)
    assert device.symbol_catalog is catalog and len(control.sessions) == 1


@pytest.fixture
def map_source(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    axf = project / 'app.elf'
    axf.write_bytes(b'elf')
    source = project / 'app.c'
    source.write_text('volatile float value = 0;\n', encoding='utf-8')
    mapping = axf.with_suffix('.map')
    mapping.write_text(' value 0x00080330 tp-0x07D0 4 4 Zero Gb app.c.o\n', encoding='utf-8')
    return axf, source, mapping


@pytest.mark.parametrize('text', ['float *value;', 'float value[1];', 'float *value = 0;',
    '// float value;\n', 'void f() { float value; }', 'typedef struct { float value; } V;',
    'float value; uint32_t value;', 'float value; float value;', 'extern float value;',
    'char *s = "float value;";', 'float other = value;',
    '#if 0\nfloat value;\n#endif', '#define float int\nfloat value;'])
def test_map_fallback_rejects_guessing_or_ambiguous_declarations(map_source, text):
    axf, source, _ = map_source
    source.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError):
        MapSourceSnapshot.load(str(axf)).resolve('value')


def test_map_search_stays_inside_explicit_root_and_snapshots_new_files(map_source):
    axf, source, _ = map_source
    source.unlink()
    outside = axf.parent.parent / 'unrelated.c'
    outside.write_text('float value;', encoding='utf-8')
    snapshot = MapSourceSnapshot.load(str(axf))
    with pytest.raises(ValueError): snapshot.resolve('value')
    source.write_text('float value;', encoding='utf-8')
    with pytest.raises(ValueError): snapshot.resolve('value')
    assert MapSourceSnapshot.load(str(axf)).resolve('value') == (0x80330, 'float', 4)


@pytest.mark.parametrize('changed', ['map', 'source', 'deleted'])
def test_map_snapshot_changes_conflict_before_memory_access(watch, map_source, changed):
    client, _, device, _, _ = watch
    axf, source, mapping = map_source
    device._axf = str(axf)
    device._symbol_catalog = SymbolCatalog.from_dwarf(DwarfInfo(), axf_path=str(axf))
    snapshot = device.symbol_catalog._map_source
    assert snapshot.resolve('value') == (0x80330, 'float', 4)
    path = mapping if changed == 'map' else source
    if changed == 'deleted':
        path.unlink()
    else:
        before = path.stat().st_mtime_ns
        text = path.read_text(encoding='utf-8')
        path.write_text(text.replace('80330', '80334').replace('float', 'int32'), encoding='utf-8')
        os.utime(path, ns=(before, before))
    response = client.post('/api/device/watch', json={'names': ['value']})
    assert response.status_code == 409, response.text
    device.read_memory.assert_not_called()


def test_map_read_variable_and_watch_share_readonly_descriptor(watch, map_source):
    client, _, device, _, _ = watch
    axf, _, _ = map_source
    device._symbol_catalog = SymbolCatalog.from_dwarf(DwarfInfo(), axf_path=str(axf))
    device.read_memory.side_effect = lambda *args: struct.pack('<f', -1.25)
    assert device.read_variable('value') == -1.25
    response = client.post('/api/device/watch', json={'names': ['value']})
    assert response.status_code == 200 and response.json()['rows'][0]['value'] == -1.25
    assert not device.symbol_catalog.read_descriptor('value').writable
    with pytest.raises(ValueError): device.write_variable('value', 1)


def test_invalid_map_type_returns_validation_error_for_single_and_batch(watch, map_source):
    client, _, device, _, _ = watch
    axf, source, _ = map_source
    source.write_text('float *value;', encoding='utf-8')
    device._symbol_catalog = SymbolCatalog.from_dwarf(DwarfInfo(), axf_path=str(axf))
    for path, body in [('read-variable', {'name': 'value'}), ('watch', {'names': ['value']})]:
        response = client.post('/api/device/' + path, json=body)
        assert response.status_code == 422, response.text
    device.read_memory.assert_not_called()


def test_map_explicit_project_root_supports_nested_build_output(map_source):
    axf, source, mapping = map_source
    build = axf.parent / 'build' / 'Obj'
    build.mkdir(parents=True)
    nested = build / axf.name
    nested.write_bytes(axf.read_bytes())
    nested.with_suffix('.map').write_bytes(mapping.read_bytes())
    with pytest.raises(ValueError): MapSourceSnapshot.load(str(nested)).resolve('value')
    source.write_text('#include <stdint.h>\nfloat value;', encoding='utf-8')
    assert MapSourceSnapshot.load(str(nested), str(axf.parent)).resolve('value') == (0x80330, 'float', 4)


@pytest.mark.parametrize('limit', ['_MAX_SOURCE_BYTES', '_MAX_SOURCE_FILES', '_MAX_ENTRIES'])
def test_source_limits_disable_only_map_fallback(watch, map_source, monkeypatch, limit):
    from mklink import watch as module
    _, _, device, _, _ = watch
    axf, _, _ = map_source
    monkeypatch.setattr(module, limit, 0)
    catalog = SymbolCatalog.from_dwarf(device._dwarf_info, axf_path=str(axf))
    assert catalog.read_descriptor('a').address == 0x20000000
    with pytest.raises(ValueError, match='limit'): catalog.read_descriptor('value')


def test_cli_watch_adopts_backend_and_sends_one_request(monkeypatch, capsys, tmp_path):
    calls = []
    class Adapter:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): calls.append(('connect', kwargs))
        def call(self, name, args):
            calls.append((name, args))
            return {'rows': [{'name': n, 'address': '0x20000000', 'type': 'float', 'size': 4, 'value': 1} for n in args['names']]}
        def close(self): calls.append(('detach', None))
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', Adapter)
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', lambda *a, **kw: pytest.fail('direct CDC'))
    profile = tmp_path / 'watch.json'
    profile.write_text(json.dumps({'variables': ['c']}), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['mklink', 'watch', 'a,b', '--probe', 'chosen', '--profile', str(profile), '--json'])
    cli.main()
    assert calls[0][1]['probe'] == 'chosen' and calls[0][1]['project_root'] is None and calls[0][1]['axf'] is None
    assert calls[1:] == [('watch', {'names': ['a', 'b', 'c']}), ('detach', None)]
    assert len(json.loads(capsys.readouterr().out)) == 3


@pytest.mark.parametrize('options', [['a', '--period', 'nan'], ['a', '--period', '-1'],
                                   ['a', '--period', 'inf'], [], ['a,a'], ['a', '--struct']])
def test_invalid_watch_cli_never_connects(monkeypatch, options):
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', lambda **kw: pytest.fail('connected'))
    monkeypatch.setattr(sys, 'argv', ['mklink', 'watch', *options])
    with pytest.raises(SystemExit) as error: cli.main()
    assert error.value.code


@pytest.mark.parametrize('body', ['{}', '{"variables":"a"}', '{"variables":[true]}',
                                '{"variables":["a"],"other":1}', 'bad-json', '汉'*30000],
                         ids=['missing', 'string', 'boolean', 'unknown-field', 'json', 'byte-limit'])
def test_invalid_profile_never_connects(monkeypatch, tmp_path, body):
    path = tmp_path / 'watch.json'
    path.write_text(body, encoding='utf-8')
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', lambda **kw: pytest.fail('connected'))
    args = SimpleNamespace(command='watch', variables=[], period=0, profile=str(path), json=True)
    with pytest.raises(SystemExit): runtime_cli.run(args)


@pytest.mark.parametrize('failure', [KeyboardInterrupt(), RuntimeErrorResponse('busy')])
def test_periodic_watch_exits_without_retry_and_only_detaches(monkeypatch, failure):
    calls = []
    class Adapter:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): calls.append('connect')
        def call(self, *args): calls.append('watch'); raise failure
        def close(self): calls.append('detach')
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', Adapter)
    args = SimpleNamespace(command='watch', variables=['a'], period=.01, profile=None, json=True)
    if isinstance(failure, KeyboardInterrupt): runtime_cli.run(args)
    else:
        with pytest.raises(SystemExit): runtime_cli.run(args)
    assert calls == ['connect', 'watch', 'detach']


def test_sdk_and_mcp_generic_watch_use_same_capability(monkeypatch):
    calls = []
    class Adapter:
        info = {}
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): return {}
        def call(self, name, arguments): calls.append((name, arguments)); return {'rows': []}
        def close(self): pass
    monkeypatch.setattr('mklink.shared_device.RuntimeClient', Adapter)
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', Adapter)
    assert SharedDevice().watch(['a']) == []
    async def run():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'selected'})
            await mcp.call_tool('gui_call', {'capability': 'watch', 'arguments': {'names': ['a']}})
    asyncio.run(run())
    assert calls == [('watch', {'names': ['a']})] * 2
