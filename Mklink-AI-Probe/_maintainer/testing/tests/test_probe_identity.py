from types import SimpleNamespace

import pytest

from mklink.probes import inventory, select_probe, set_alias
from mklink.runtime import RuntimeErrorResponse, runtime_dir, runtime_lock


def port(name, serial, location='1-1:x.4'):
    return SimpleNamespace(device=name, serial_number=serial, location=location, vid=0x0D28, pid=0x0202,
                           description='Test probe', interface=None, hwid=f'USB MI_04 SER={serial}')


def test_alias_survives_com_renumbering_and_usb_location_change(monkeypatch, tmp_path):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path))
    ports = [port('COM10', 'test-unique-a')]
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: ports)
    before = inventory()[0]['probe_id']
    assert set_alias('COM10', '电机板')['firmware_changed'] is False
    ports[:] = [port('COM99', 'test-unique-a', '1-8:x.4')]
    selected = select_probe('电机板')
    assert selected['port'] == 'COM99'
    assert selected['probe_id'] == before


def test_two_probes_require_explicit_selection_and_unique_aliases(monkeypatch, tmp_path):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [port('COM10', 'a'), port('COM20', 'b')])
    with pytest.raises(RuntimeErrorResponse, match='Multiple probes'):
        select_probe()
    assert select_probe(allow_lobby=True)['probe_id'] == 'lobby'
    first = set_alias('COM10', 'left')
    with pytest.raises(RuntimeErrorResponse, match='already assigned'):
        set_alias('COM20', 'LEFT')
    assert select_probe(first['probe_id'])['port'] == 'COM10'
    with pytest.raises(RuntimeErrorResponse, match='missing or ambiguous'):
        select_probe('unknown')


def test_duplicate_serials_are_separate_but_cannot_get_persistent_alias(monkeypatch, tmp_path):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [port('COM10', 'duplicate'), port('COM20', 'duplicate', '1-2:x.4')])
    probes = inventory()
    assert probes[0]['probe_id'] != probes[1]['probe_id']
    assert not any(p['identity_stable'] for p in probes)
    with pytest.raises(RuntimeErrorResponse, match='unique USB serial'):
        set_alias('COM10', 'left')


def test_runtime_owner_locks_are_per_probe_and_exclusive(monkeypatch, tmp_path):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path))
    first, second = 'usb-' + '1'*24, 'usb-' + '2'*24
    with runtime_lock('owner.lock', first), runtime_lock('owner.lock', second):
        with pytest.raises(RuntimeErrorResponse):
            with runtime_lock('owner.lock', first):
                pytest.fail('same physical probe must have one owner')
    assert runtime_dir(first) != runtime_dir(second)
    with pytest.raises(RuntimeErrorResponse, match='Invalid probe'):
        runtime_dir('../escape')


def test_simultaneous_clients_reuse_one_worker_but_other_probe_is_independent(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import time
    from mklink.runtime import discover, ensure_runtime, request
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path / 'registry'))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [port('COM10', 'a'), port('COM20', 'b')])
    first, second = inventory()
    workers = []
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(ensure_runtime, project_root=str(tmp_path), probe=first['probe_id']) for _ in range(2)]
            pair = [future.result() for future in futures]
        workers.append(pair[0])
        assert pair[0]['instance_id'] == pair[1]['instance_id']
        other = ensure_runtime(project_root=str(tmp_path), probe=second['probe_id'])
        workers.append(other)
        assert other['pid'] != pair[0]['pid']
        assert other['port'] != pair[0]['port']
        request(pair[0], 'POST', '/_runtime/stop', {'confirm': True})
        assert request(other, 'GET', '/_runtime/status')['probe_id'] == second['probe_id']
    finally:
        for info in workers:
            try:
                request(info, 'POST', '/_runtime/stop', {'confirm': True})
            except RuntimeErrorResponse:
                pass
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not any((runtime_dir(info['probe_id']) / 'endpoint.json').exists() for info in workers):
                break
            time.sleep(.1)
        assert not any((runtime_dir(info['probe_id']) / 'endpoint.json').exists() for info in workers)
