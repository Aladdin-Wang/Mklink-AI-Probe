"""Every stable build change awaits explicit reload; running captures stay untouched."""
import asyncio
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mklink.remote import api, dashboards
from mklink.runtime_api import install_runtime, Session
from mklink.symbol_catalog import SymbolCatalog
from mklink.dwarf_parser import DwarfInfo, DwarfVariable
from mklink.superwatch import SuperWatchRuntime, WatchItem
from test_remote_api import _connected_symbol_device


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboards, '_managers', {})
    device, axf = _connected_symbol_device(tmp_path)
    device._axf = str(axf)
    device._project_root = str(tmp_path)
    device._port = None
    app = api.create_app(auth_token=None, project_root=str(tmp_path))
    app.state.mklink_state['device'] = device
    control = install_runtime(app, {'port': 8765, 'token': 'fixture', 'instance_id': 'fixture'})
    return app, device, axf, control


def test_background_linker_replacement_is_silent_and_recovers_after_persistent_error(source, monkeypatch):
    app, device, axf, control = source
    now = [0.0]
    monkeypatch.setattr('mklink.source_monitor.time.monotonic', lambda: now[0])
    parses = []

    def config(*args, **kwargs):
        if not axf.exists():
            raise ValueError('symbol file unavailable')
        return {'rtt_addr': '0x20000020'}

    def parse(*args, **kwargs):
        parses.append(axf.read_bytes())
        device.symbol_catalog = SymbolCatalog.from_dwarf(device._dwarf_info, axf_path=str(axf), generation=2)
        return {'loaded': True}

    monkeypatch.setattr('mklink.project_config.ensure_rtt_config_updated', config)
    monkeypatch.setattr(device, 'parse_axf', parse)

    def poll(at):
        now[0] = at
        asyncio.run(app.state.check_file_sources(background=True))

    poll(0)
    axf.unlink()  # Keil briefly removes the output while linking.
    poll(1)
    axf.write_bytes(b'partial output')
    poll(2)
    axf.write_bytes(b'complete output')
    poll(3)
    poll(4)
    assert app.state.mklink_state['file_source_change'] is None and parses == []
    poll(5)
    first = dict(app.state.mklink_state['file_source_change'])
    assert first['state'] == 'awaiting-reload' and parses == []
    poll(10)
    assert app.state.mklink_state['file_source_change']['sequence'] == first['sequence']
    asyncio.run(app.state.check_file_sources(apply=True))
    assert parses == [b'complete output']
    axf.unlink()
    poll(11)
    poll(16)
    assert app.state.mklink_state['file_source_change']['state'] == 'awaiting-reload'
    assert len(parses) == 1
    axf.write_bytes(b'next complete build')
    poll(17)
    poll(19)
    assert app.state.mklink_state['file_source_change']['state'] == 'awaiting-reload'
    assert len(parses) == 1
    asyncio.run(app.state.check_file_sources(apply=True))
    assert parses == [b'complete output', b'next complete build']


@pytest.mark.parametrize('address', ['0x20000020', '0x20000040', None])
def test_live_rtt_restarts_only_for_changed_address_and_retains_subscribers(source, monkeypatch, address):
    app, device, axf, control = source
    rtt = dashboards.get_managers()['rtt']
    rtt._running = True
    rtt._start_info = {'control_block_addr': '0x20000020'}
    rtt._start_options = {'addr': '0x20000020', 'all_channels': True}
    control.sessions['reader'] = Session(str(axf.parent), None, streams={'rtt'})
    control.created_streams['rtt'] = 'reader'
    actions = []
    def stop(*args, **kwargs):
        actions.append('stop')
        rtt._running = False
    def start(dev, **options):
        assert dev is device and options['addr'] == address and options['all_channels']
        actions.append('start')
        rtt._running = True
    def parse(*args, **kwargs):
        actions.append('parse')
        device.symbol_catalog = SymbolCatalog.from_dwarf(device._dwarf_info, axf_path=str(axf), generation=2)
        return {'loaded': True}
    monkeypatch.setattr(rtt, 'stop', stop)
    monkeypatch.setattr(rtt, 'start', start)
    monkeypatch.setattr(device, 'parse_axf', parse)
    monkeypatch.setattr(api, 'acquire_dashboard_resources', lambda *args: [])
    monkeypatch.setattr('mklink.project_config.ensure_rtt_config_updated', lambda *args, **kw: {'rtt_addr': address})
    axf.write_bytes(b'new build')
    asyncio.run(app.state.check_file_sources())
    event = app.state.mklink_state['file_source_change']
    assert event['state'] == 'awaiting-reload' and actions == []
    assert rtt.running and device.symbol_catalog.generation == 1
    asyncio.run(app.state.check_file_sources())
    assert actions == []
    response = TestClient(app, base_url='http://127.0.0.1:8765',
                          headers={'X-Auth-Token': 'fixture'}).post('/api/symbols/reload-sources')
    assert response.status_code == (409 if address is None else 200), response.text
    event = app.state.mklink_state['file_source_change']
    if address is None:
        assert actions == ['stop', 'parse'] and event['state'] == 'failed'
        assert not rtt.running
    elif address == '0x20000020':
        assert actions == ['parse'] and event['state'] == 'applied'
        assert not event['rtt_changed'] and not event['rtt_restarted']
        assert rtt.running
    else:
        assert actions == ['stop', 'parse', 'start'] and event['rtt_restarted']
        assert rtt.running
        actions.clear()
        rtt._restart_after_operation()
        assert actions == ['start']  # Later flash restoration uses the new address.
    assert control.created_streams['rtt'] == 'reader'
    assert control.sessions['reader'].streams == {'rtt'}


@pytest.mark.parametrize('cancel', [False, True])
def test_reload_restores_invalidated_capture_but_respects_explicit_stop(source, monkeypatch, cancel):
    app, device, axf, control = source
    rtt = dashboards.get_managers()['rtt']
    rtt._running = True
    rtt._start_info = {'control_block_addr': '0x20000020'}
    rtt._start_options = {'addr': '0x20000020', 'all_channels': True}
    def parse(*args, **kwargs):
        device.symbol_catalog = SymbolCatalog.from_dwarf(device._dwarf_info, axf_path=str(axf), generation=2)
        return {'loaded': True}
    monkeypatch.setattr(device, 'parse_axf', parse)
    monkeypatch.setattr('mklink.project_config.ensure_rtt_config_updated', lambda *a, **kw: {'rtt_addr': '0x20000040'})
    monkeypatch.setattr(api, 'acquire_dashboard_resources', lambda *args: [])
    start = Mock()
    monkeypatch.setattr(rtt, 'start', start)
    axf.write_bytes(b'new build before download')
    asyncio.run(app.state.check_file_sources())
    assert app.state.mklink_state['file_source_change']['state'] == 'awaiting-reload'
    assert rtt.running
    asyncio.run(app.state.check_file_sources())
    start.assert_not_called()
    if cancel:
        asyncio.run(api.stop_dashboard_manager_transaction(app.state.mklink_state, 'rtt', rtt))
    else:
        rtt._running = False  # IDE download invalidates a worker without a user stop.
        rtt._start_info = {}
    asyncio.run(app.state.check_file_sources(apply=True))
    assert app.state.mklink_state['file_source_change']['state'] == 'applied'
    if cancel:
        start.assert_not_called()
    else:
        start.assert_called_once_with(device, addr='0x20000040', all_channels=True, encoding='utf-8', mode=0, search_size=0)


@pytest.mark.parametrize('paused', [False, True])
def test_monitor_rebinds_superwatch_addresses_removes_renamed_items_and_restores_pause(source, monkeypatch, paused):
    app, device, axf, control = source
    manager = dashboards.get_managers()['superwatch']
    manager._runtime = SuperWatchRuntime(
        items=[WatchItem('gain', 0x20000010, 'float', 4), WatchItem('removed', 0x20000030, 'float', 4)],
        dwarf_info=device._dwarf_info, symbol_catalog=device.symbol_catalog)
    manager._device = device
    manager._running = True
    if not paused:
        manager._collecting.set()
    actions = []
    def stop():
        actions.append('stop')
        manager._running = False
        manager._collecting.clear()
    def start(dev):
        actions.append('start')
        manager._running = True
        manager._collecting.set()
    def parse(*args):
        assert not manager.running
        actions.append('parse')
        info = DwarfInfo(base_types={1: ('float', 4)}, variables={
            'gain': DwarfVariable('gain', 10, 1, 0x20000040, 4, 'float'),
            'renamed': DwarfVariable('renamed', 11, 1, 0x20000030, 4, 'float'),
        })
        device._dwarf_info = info
        device.symbol_catalog = SymbolCatalog.from_dwarf(info, axf_path=str(axf), generation=2,
                                                        ram_ranges=[(0x20000000, 0x20010000)])
        return device.symbol_catalog
    device.reparse_axf_atomically = parse
    def preview():
        info = DwarfInfo(base_types={1: ('float', 4)}, variables={
            'gain': DwarfVariable('gain', 10, 1, 0x20000040, 4, 'float'),
            'renamed': DwarfVariable('renamed', 11, 1, 0x20000030, 4, 'float'),
        })
        return SymbolCatalog.from_dwarf(info, axf_path=str(axf), generation=2,
                                       ram_ranges=[(0x20000000, 0x20010000)])
    device.preview_axf_catalog = preview
    monkeypatch.setattr(manager, 'stop', stop)
    monkeypatch.setattr(manager, 'start', start)
    monkeypatch.setattr('mklink.project_config.ensure_rtt_config_updated', lambda *a, **kw: {})
    axf.write_bytes(b'recompiled')
    asyncio.run(app.state.check_file_sources())
    assert app.state.mklink_state['file_source_change']['state'] == 'awaiting-reload'
    assert actions == [] and manager._runtime.items[0].address == 0x20000010
    asyncio.run(app.state.check_file_sources(apply=True))
    assert actions == ['stop', 'parse', 'start']
    assert [(item.name, item.address) for item in manager._runtime.items] == [('gain', 0x20000040)]
    assert manager.running and manager._collecting.is_set() == (not paused)
    event = app.state.mklink_state['file_source_change']
    assert event['state'] == 'applied' and event['symbols_reloaded']
    assert event['rebind']['removed'] == ['removed']

def test_timestamp_only_rebuild_requires_manual_reload_without_preview(source, monkeypatch):
    import os
    app, device, axf, control = source
    preview = Mock(side_effect=AssertionError('background parsing is forbidden'))
    monkeypatch.setattr(device, 'preview_axf_catalog', preview, raising=False)
    parse = Mock(side_effect=AssertionError('background reloading is forbidden'))
    monkeypatch.setattr(device, 'parse_axf', parse)
    asyncio.run(app.state.check_file_sources())
    stat = axf.stat()
    os.utime(axf, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
    asyncio.run(app.state.check_file_sources())
    assert app.state.mklink_state['file_source_change']['state'] == 'awaiting-reload'
    assert device.symbol_catalog.generation == 1
    preview.assert_not_called()
    parse.assert_not_called()


@pytest.mark.parametrize('fail_after_parse', [False, True])
def test_explicit_browser_snapshot_reload_uses_shared_transaction(source, monkeypatch, fail_after_parse):
    app, device, axf, control = source
    uploaded = axf.with_name('new-upload.axf')
    uploaded.write_bytes(b'uploaded rebuilt firmware')
    parses = []
    configs = []

    def parse(path, **kwargs):
        parses.append(path)
        device._axf = path
        device.symbol_catalog = SymbolCatalog.from_dwarf(device._dwarf_info, axf_path=path, generation=2)
        return {'loaded': True, 'axf_path': path}

    def config(*args, **kwargs):
        configs.append(kwargs['source_path'])
        if fail_after_parse and len(configs) == 2:
            raise OSError('configuration storage temporarily unavailable')
        return {'rtt_addr': '0x20000040'}

    monkeypatch.setattr(device, 'parse_axf', parse)
    monkeypatch.setattr('mklink.project_config.ensure_rtt_config_updated', config)
    asyncio.run(app.state.check_file_sources())
    assert parses == [] and device._axf == str(axf)
    client = TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'fixture'})
    result = client.post('/api/symbols/reload-sources', params={
        'source_path': str(uploaded), 'expected_axf': str(axf)})
    if fail_after_parse:
        assert result.status_code == 409 and device._axf == str(uploaded)
        result = client.post('/api/symbols/reload-sources', params={
            'source_path': str(uploaded), 'expected_axf': str(axf)})
    assert result.status_code == 200, result.text
    assert result.json()['state'] == 'applied'
    assert result.json()['axf_path'] == str(uploaded)
    attempts = 2 if fail_after_parse else 1
    assert parses == [str(uploaded)] * attempts and configs == [str(uploaded)] * (attempts * 2)
    assert device.symbol_catalog.generation == 2
    # A stale browser must not replace a source activated by another client.
    result = client.post('/api/symbols/reload-sources', params={
        'source_path': str(axf), 'expected_axf': str(axf)})
    assert result.status_code == 409
    assert parses == [str(uploaded)] * attempts


def test_browser_snapshot_reload_requires_connected_target(source):
    app, device, axf, control = source
    device.connected = False
    client = TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'fixture'})
    result = client.post('/api/symbols/reload-sources', params={
        'source_path': str(axf), 'expected_axf': str(axf)})
    assert result.status_code == 409
