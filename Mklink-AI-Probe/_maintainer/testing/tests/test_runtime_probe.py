"""Probe queries share admission without creating a target Device/session."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from mklink._types import DeviceState
from mklink.remote.resource_manager import ResourceGroup
from mklink.runtime import RuntimeErrorResponse
from mklink.runtime_api import install_runtime
from mklink.remote.api import create_app
from test_power_telemetry import Bridge, wire


@pytest.fixture
def probe(monkeypatch, tmp_path):
    app = create_app(auth_token=None, project_root=str(tmp_path))
    state = app.state.mklink_state
    selected = {'probe_id': 'test-probe', 'port': 'COM9'}
    monkeypatch.setattr('mklink.probes.inventory', lambda: [selected])
    monkeypatch.setattr('mklink.probes.select_probe', lambda selector: selected)
    managers = {'rtt': SimpleNamespace(running=False)}
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: managers)
    bridge = Bridge()
    calls = []
    def constructor(port):
        calls.append(('open', port))
        return bridge
    def connect(**kwargs):
        calls.append(('connect', kwargs))
        return True
    bridge.connect = connect
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', constructor)
    def forbidden(*args, **kwargs):
        raise AssertionError('Probe query created a target Device')
    monkeypatch.setattr('mklink.device.Device', forbidden)
    info = {'port': 8765, 'token': 'test-secret', 'instance_id': 'test-instance', 'probe_id': selected['probe_id']}
    control = install_runtime(app, info)
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': info['token']}) as client:
        yield client, control, state, bridge, calls, managers, selected
        state['device'] = None  # fake devices have no shutdown workers


@pytest.mark.parametrize('supported', [True, False])
def test_shared_firmware_upgrade_routes_bound_volumes_and_manual_fallback(probe, monkeypatch, tmp_path, supported):
    from mklink import firmware_check as fc
    client, control, state, bridge, calls, _, selected = probe
    selected.update(identity_stable=True, vid=0xd28, pid=0x202, serial_number='0123456789abcdef')
    class Volumes:
        def __init__(self, probe): assert probe is selected
        def find(self, *, bootloader=False): return 'boot' if bootloader else 'application'
    monkeypatch.setattr('mklink.probe_volumes.FirmwareVolumes', Volumes)
    def enter():
        calls.append('enter')
        if not supported: raise RuntimeError('Old firmware has no command')
    bridge.enter_bootloader = enter
    def upgrade(device, root, *, confirm, disk_reader, bootloader_finder):
        assert confirm is True and disk_reader() == 'application' and bootloader_finder() == 'boot'
        try: device.enter_bootloader()
        except RuntimeError: return {'status': 'manual_required'}
        return {'status': 'updated'}
    monkeypatch.setattr(fc, 'upgrade_probe_firmware', upgrade)
    result = client.post('/api/probe/firmware-upgrade', json=True)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == ('updated' if supported else 'manual_required')
    assert calls == [('open', 'COM9'), ('connect', {'recover_stream': False}), 'enter']
    assert bridge.closed and not control.sessions and not state['resource_manager'].get_status()


def test_lobby_upgrade_offers_manual_download_without_opening_a_probe(probe):
    client, _, state, _, calls, _, _ = probe
    state['shared_probe_id'] = 'lobby'
    result = client.post('/api/probe/firmware-upgrade', json=True)
    assert result.status_code == 200 and result.json()['status'] == 'manual_required'
    assert not calls


@pytest.mark.parametrize('busy', ['capture', 'client', 'job', 'uart_capture', 'uart_client'])
def test_probe_update_still_protects_active_users_and_jobs(probe, monkeypatch, busy):
    client, control, _, _, calls, managers, _ = probe
    monkeypatch.setattr('mklink.runtime_probe.upgrade_firmware', lambda *a: pytest.fail('Unsafe update reached worker'))
    if busy == 'capture': managers['rtt'].running = True
    elif busy == 'uart_capture': managers['serial'] = SimpleNamespace(running=True)
    elif busy == 'job': monkeypatch.setattr(control, 'job_busy', lambda: True)
    else:
        from mklink.runtime_api import Session
        control.sessions['ai'] = Session('.', None, scope='uart' if busy == 'uart_client' else 'target')
    assert client.post('/api/probe/firmware-upgrade', json=True).status_code == 409
    assert not calls


def test_uart_operations_cannot_start_during_probe_upgrade(probe):
    client, control, _, _, calls, _, _ = probe
    control.current_operation = {'path': '/api/probe/firmware-upgrade'}
    try:
        response = client.post('/api/dash/serial/start', json={'ports': []})
        assert response.status_code == 409 and not calls
    finally:
        control.current_operation = None


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('disk_version', [False, True])
def test_firmware_recheck_reuses_probe_query_only_when_disk_version_is_unavailable(probe, monkeypatch, tmp_path, existing, disk_version):
    from mklink import firmware_check as fc
    client, control, state, bridge, calls, _, _ = probe
    if existing:
        state['device'] = SimpleNamespace(connected=True, port='COM9', _bridge=bridge)
    bridge.response = 'V4.5.2\n>>> '
    (tmp_path/'MicroLink_V4.5.2.uf2').write_bytes(b'test-index-entry')
    disk = tmp_path/'disk'
    disk.mkdir()
    (disk/'readme.txt').write_text('V4.5.2\n', encoding='utf-8')
    monkeypatch.setattr(fc, '_resolve_firmware_root', lambda: tmp_path)
    monkeypatch.setattr(fc, '_remote_firmwares', lambda: None)
    monkeypatch.setattr(fc, '_probe_disk', lambda: str(disk) if disk_version else None)
    def forbidden(port):
        raise AssertionError('Firmware recheck attempted an independent CDC connection')
    monkeypatch.setattr(fc, 'read_device_version', forbidden)
    response = client.get('/api/probe/firmware-check')
    assert response.status_code == 200 and response.json()['status'] == 'ok', response.text
    assert response.json()['current_version'] == 'V4.5.2'
    assert bridge.commands == ([] if disk_version else ['cmd.get_version()'])
    assert not control.sessions and not state['resource_manager'].get_status()
    if disk_version:
        assert not calls and not bridge.closed
    else:
        assert calls == ([] if existing else [('open','COM9'), ('connect', {'recover_stream': False})])
        assert bridge.closed is (not existing)


@pytest.mark.parametrize('failure', ['busy', 'missing', 'job'])
def test_firmware_check_get_obeys_hardware_admission_before_catalog_or_disk_io(probe, monkeypatch, failure):
    from mklink import firmware_check as fc
    client, control, _, bridge, calls, managers, _ = probe
    if failure == 'busy':
        managers['rtt'].running = True
    elif failure == 'missing':
        monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    else:
        monkeypatch.setattr(control, 'job_busy', lambda: True)
    monkeypatch.setattr(fc, 'check_probe_firmware', lambda *a, **kw: calls.append('check'))
    response = client.get('/api/probe/firmware-check')
    assert response.status_code == 409, response.text
    assert not calls and not bridge.commands


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('capability', ['power-read', 'version'])
def test_probe_query_uses_only_selected_bridge_and_releases_own_resources(probe, existing, capability):
    client, control, state, bridge, calls, _, _ = probe
    if existing:
        state['device'] = SimpleNamespace(connected=True, port='COM9', _bridge=bridge)
    if capability == 'version':
        bridge.response = 'V4.5.2\n>>> '
    response = client.post('/api/probe/' + capability)
    assert response.status_code == 200, response.text
    assert response.json() == ({'raw': bridge.response} if capability == 'version' else dict(
        voltage_mv=3300, current_ma=12.345, power_mw=40.739, current_supported=True, sample_age_ms=10))
    assert bridge.commands == ['cmd.get_version()' if capability == 'version' else 'cmd.get_power()']
    assert calls == ([] if existing else [('open', 'COM9'), ('connect', {'recover_stream': False})])
    assert bridge.closed is (not existing)
    assert not control.sessions and not state['resource_manager'].get_status()
    assert (state['device'] is not None) is existing


@pytest.mark.parametrize('failure', ['busy', 'init', 'missing', 'stale', 'port_changed', 'job', 'unauthenticated'])
@pytest.mark.parametrize('capability', ['power-read', 'idcode'])
def test_conflicts_fail_before_opening_or_interrupting_probe(probe, monkeypatch, failure, capability):
    client, control, state, bridge, calls, managers, selected = probe
    headers = {}
    if failure == 'busy':
        managers['rtt'].running = True
    elif failure == 'init':
        state['resource_manager'].acquire(ResourceGroup.TARGET_DEBUG, 'user:init')
    elif failure == 'missing':
        monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    elif failure in {'stale', 'port_changed'}:
        state['device'] = SimpleNamespace(connected=failure == 'port_changed', port='COM8', _bridge=bridge)
    elif failure == 'job':
        monkeypatch.setattr(control, 'job_busy', lambda: True)
    else:
        headers = {'X-Auth-Token': 'wrong'}
    before = state['resource_manager'].get_status()
    response = client.post('/api/probe/' + capability, headers=headers)
    assert response.status_code == (401 if failure == 'unauthenticated' else 409), response.text
    assert calls == bridge.commands == [] and not bridge.closed
    assert state['resource_manager'].get_status() == before
    if failure == 'busy':
        assert managers['rtt'].running


@pytest.mark.parametrize('failure', ['old_firmware', 'timeout', 'handshake', 'not_ready'])
def test_failure_closes_temporary_bridge_without_retry_or_target_session(probe, failure):
    client, control, state, bridge, calls, _, _ = probe
    if failure == 'old_firmware':
        bridge.response = 'AttributeError: get_power\n>>> '
    elif failure == 'timeout':
        def timeout(command, timeout):
            bridge.commands.append(command)
            raise TimeoutError('query outcome unknown')
        bridge.send_command = timeout
    elif failure == 'handshake':
        bridge.connect = lambda **kwargs: False
    else:
        bridge.state = DeviceState.DUMP_STREAM
    response = client.post('/api/probe/power-read')
    assert response.status_code in (400, 409), response.text
    assert bridge.commands == (['cmd.get_power()'] if failure in {'old_firmware', 'timeout'} else [])
    assert bridge.closed and state['device'] is None
    assert not control.sessions and not state['resource_manager'].get_status()


def test_client_query_does_not_attach_or_retry(monkeypatch):
    from mklink import runtime
    calls = []
    info = {'port': 8765, 'token': 'secret'}
    def ensure(**kwargs):
        calls.append(('select', kwargs))
        return info
    def request(endpoint, method, path, body):
        calls.append((endpoint, method, path, body))
        raise RuntimeErrorResponse('failed once')
    monkeypatch.setattr(runtime, 'ensure_runtime', ensure)
    monkeypatch.setattr(runtime, 'request', request)
    with pytest.raises(ValueError):
        runtime.query_probe('halt', probe='chosen')
    assert not calls
    with pytest.raises(RuntimeErrorResponse):
        runtime.query_probe('power_read', probe='chosen')
    assert calls == [('select', {'probe': 'chosen', 'device_port': None}), (info, 'POST', '/api/probe/power-read', {})]
    calls.clear()
    with pytest.raises(RuntimeErrorResponse):
        runtime.query_probe('probe_version', info=info)
    assert calls == [(info, 'POST', '/api/probe/version', {})]


def test_cancelled_request_keeps_admission_until_worker_closes_bridge(probe):
    import threading
    client, control, state, bridge, _, _, _ = probe
    started, finish = threading.Event(), threading.Event()
    def slow(command, timeout):
        started.set()
        assert finish.wait(5)
        return wire()
    bridge.send_command = slow
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url=str(client.base_url), headers=client.headers) as http:
            task = asyncio.create_task(http.post('/api/probe/power-read'))
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(.02)
            assert not task.done() and control.operation_lock.locked()
            assert (await http.post('/api/probe/version')).status_code == 409
            assert state['resource_manager'].get_status() and not bridge.closed
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not control.operation_lock.locked() and bridge.closed
            assert not state['resource_manager'].get_status()
    try:
        asyncio.run(scenario())
    finally:
        finish.set()

@pytest.mark.parametrize('existing', [False, True])
def test_idcode_query_borrows_only_selected_bridge(probe, existing):
    client, control, state, bridge, calls, _, _ = probe
    if existing:
        state['device'] = SimpleNamespace(connected=True, port='COM9', _bridge=bridge)
    def read(command, **kwargs):
        bridge.commands.append(command)
        return 'idcode = 0X1BA01477\n>>> '
    bridge.send_command = read
    response = client.post('/api/probe/idcode')
    assert response.status_code == 200, response.text
    assert response.json() == {'idcode': 0x1ba01477}
    assert bridge.commands == ['cmd.get_idcode()']
    assert calls == ([] if existing else [('open', 'COM9'), ('connect', {'recover_stream': False})])
    assert bridge.closed is (not existing)
    assert not control.sessions and not state['resource_manager'].get_status()


@pytest.mark.parametrize('failure', ['busy', 'missing', 'wrong_port'])
def test_mcu_discovery_rejects_conflict_before_discovery_or_writes(probe, monkeypatch, failure):
    client, control, state, bridge, calls, managers, _ = probe
    if failure == 'busy':
        managers['rtt'].running = True
    elif failure == 'missing':
        monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    def forbidden(**kwargs):
        raise AssertionError('Discovery ran before admission')
    monkeypatch.setattr('mklink.mcu_detect.inspect_mcu', forbidden)
    response = client.post('/api/mcu-detect', json={'port': 'COM8' if failure == 'wrong_port' else 'COM9'})
    assert response.status_code == 409, response.text
    assert not calls and not bridge.commands


def test_mcu_discovery_uses_internal_query_without_recursive_http(probe, monkeypatch):
    client, _, state, bridge, calls, _, _ = probe
    state['device'] = SimpleNamespace(connected=True, port='COM9', _bridge=bridge)
    bridge.send_command = lambda *args, **kwargs: 'idcode = 0X1BA01477\n'
    def forbidden(*args, **kwargs):
        raise AssertionError('Backend called its own HTTP query')
    monkeypatch.setattr('mklink.runtime.query_probe', forbidden)
    def detect(**kwargs):
        return {'idcode': kwargs['idcode_reader'](kwargs['port'])}
    monkeypatch.setattr('mklink.mcu_detect.inspect_mcu', detect)
    response = client.post('/api/mcu-detect', json={'port': 'COM9'})
    assert response.status_code == 200, response.text
    assert response.json() == {'idcode': 0x1ba01477}
    assert not calls and not bridge.closed
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('existing', [False, True])
def test_failed_idcode_keeps_borrowed_session_and_releases_query_lease(probe, monkeypatch, existing):
    from mklink.flash import IDCODEError
    client, _, state, bridge, _, _, _ = probe
    if existing:
        state['device'] = SimpleNamespace(connected=True, port='COM9', _bridge=bridge)
    def fail(self):
        raise IDCODEError('no valid IDCODE')
    monkeypatch.setattr('mklink.flash.MKLinkFlash.get_idcode', fail)
    response = client.post('/api/probe/idcode')
    assert response.status_code == 400, response.text
    assert 'no valid IDCODE' in response.text
    assert bridge.closed is (not existing)
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('selector,expected', [(None, 'needs_selection'), ('same.FLM', 'needs_selection'),
                                               ('second', 'detected'), ('absent', 'error')])
def test_mcu_inspection_reuses_catalog_without_profile_or_disk_writes(tmp_path, monkeypatch, selector, expected):
    from mklink.mcu_detect import inspect_mcu
    from mklink.cmsis_dap.algorithm_catalog import FlashAlgorithm
    algorithms = [FlashAlgorithm(key, 'TEST123', 'same.FLM', 0x08000000, size, 0x20000000,
                                 32768, True, 'custom-flm', key, key, page_size=4096,
                                 sector_sizes=((0, 8192),)) for key, size in [('first', 65536), ('second', 131072)]]
    queries = []
    def catalog(target, **kwargs):
        queries.append(target)
        return algorithms
    monkeypatch.setattr('mklink.cmsis_dap.algorithm_catalog.discover_flash_algorithms', catalog)
    monkeypatch.setattr('mklink.discovery.find_microkeen_disk', lambda: pytest.fail('Inspection touched probe disk'))
    monkeypatch.setattr('mklink.runtime.query_probe', lambda *a, **kw: pytest.fail('Inspection opened CDC'))
    result = inspect_mcu(project_root=str(tmp_path), device='TEST123', flm=selector)
    assert queries == ['TEST123'] and result['status'] == expected
    assert result['profile_written'] is False and result['flm_copied'] is False
    assert not list(tmp_path.iterdir())
    if selector == 'second':
        assert result['selected_algorithm']['size'] == 131072
        assert result['selected_algorithm']['page_size'] == 4096
        assert result['selected_algorithm']['sector_sizes'] == [(0, 8192)]
        assert 'swd_clock_default' not in result


def test_hpm_inspection_uses_rom_without_flm_and_idcode_is_optional(monkeypatch):
    from mklink.mcu_detect import inspect_mcu
    monkeypatch.setattr('mklink.cmsis_dap.algorithm_catalog.discover_flash_algorithms', lambda *a, **k: pytest.fail('HPM looked for FLM'))
    assert inspect_mcu(device='HPM6E80')['backend'] == 'hpm-rom'
    assert inspect_mcu(device='HPM6E80', flm='wrong.FLM')['status'] == 'error'
    calls = []
    def query(capability, **kwargs):
        calls.append((capability, kwargs))
        return {'idcode': 0x1000563d}
    monkeypatch.setattr('mklink.runtime.query_probe', query)
    result = inspect_mcu(device='HPM6E80', port='COM9', read_idcode=True)
    assert result['idcode'] == 0x1000563d
    assert calls == [('probe_idcode', {'port': 'COM9'})]


@pytest.mark.parametrize('field', ['write_profile', 'copy_flm', 'profiles_path'])
def test_mcu_api_rejects_removed_write_options(probe, field):
    client, _, _, bridge, calls, _, _ = probe
    response = client.post('/api/mcu-detect', json={'device': 'HPM6E80', field: True})
    assert response.status_code == 422
    assert not calls and not bridge.commands
