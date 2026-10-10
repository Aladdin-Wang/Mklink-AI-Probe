"""Permission fallback preserves physical USB binding and fail-closed selection."""
import os
from types import SimpleNamespace

import pytest

from mklink import probe_volumes as volumes, windows_volumes as native


@pytest.mark.skipif(os.name != 'nt', reason='Windows dispatch')
def test_wmi_access_denied_falls_back_without_weakening_identity(monkeypatch):
    monkeypatch.setattr(volumes.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stderr='Get-CimInstance: Access denied HRESULT 0x80041003'))
    row = {'root': 'verified-guid', 'usb_identity': (1, 2, 'serial')}
    monkeypatch.setattr(native, 'volume_inventory', lambda: [row])
    assert volumes.volume_inventory() == [row]


@pytest.mark.skipif(os.name != 'nt', reason='Windows dispatch')
def test_both_inventory_errors_keep_stage_and_permission_details(monkeypatch):
    monkeypatch.setattr(volumes.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stderr='Access denied HRESULT 0x80041003'))
    def denied():
        raise OSError('WinError 5')
    monkeypatch.setattr(native, 'volume_inventory', denied)
    with pytest.raises(RuntimeError, match='before disk selection') as caught:
        volumes.volume_inventory()
    assert '0x80041003' in str(caught.value) and 'WinError 5' in str(caught.value)
    assert 'unknown flash job' in str(caught.value)


@pytest.fixture
def inventory(monkeypatch):
    api = SimpleNamespace(
        disks=lambda: [('disk-a', 'usb-a'), ('disk-b', 'usb-b'), ('disk-c', 'internal')],
        volumes=lambda: ['root-a\\', 'root-b\\', 'internal\\'],
        metadata=lambda root: ('MICROKEEN', 'G:'),
    )
    numbers = {'disk-a': (7, 1), 'disk-b': (7, 2), 'root-a': (7, 1), 'root-b': (7, 2), 'internal': (7, 3)}
    api.device_number = lambda path: numbers[path]
    monkeypatch.setattr(native, '_WindowsInventory', lambda: api)
    monkeypatch.setattr(volumes, 'usb_ancestor', lambda instance: {
        'usb-a': (1, 2, 'first'), 'usb-b': (1, 2, 'second')}.get(instance))
    return api, numbers


def test_same_labels_and_letters_are_not_used_to_join_disks(inventory):
    rows = native.volume_inventory()
    assert [(r['root'], r['usb_identity']) for r in rows] == [
        ('root-a\\', (1, 2, 'first')), ('root-b\\', (1, 2, 'second'))]


def test_ambiguous_device_number_never_selects_first_disk(inventory):
    api, numbers = inventory
    numbers['disk-b'] = (7, 1)
    with pytest.raises(OSError, match='Ambiguous'):
        native.volume_inventory()


def test_unplug_replug_during_metadata_rejects_stale_join(inventory):
    api, numbers = inventory
    def moved(root):
        numbers['disk-a'] = (7, 99)
        return 'MICROKEEN', 'G:'
    api.metadata = moved
    with pytest.raises(OSError, match='changed during enumeration'):
        native.volume_inventory()


def test_permission_failure_cannot_masquerade_as_empty_success(inventory):
    api, _ = inventory
    def denied(path):
        raise PermissionError('metadata denied')
    api.device_number = denied
    with pytest.raises(OSError, match='metadata denied'):
        native.volume_inventory()
