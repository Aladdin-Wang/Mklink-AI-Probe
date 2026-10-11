"""SVD preferences survive relocation and cannot block a target connection."""
import json
from types import SimpleNamespace

import pytest

from mklink.peripheral_watch import SvdTarget, load_catalog, save_catalog_selection
from mklink.remote.dashboards import SuperWatchStreamManager
from mklink.superwatch import WatchItem
from test_peripheral_watch import SVD


def target_at(root, pack='Vendor.DFP@1'):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'chip.svd').write_bytes(SVD)
    return SvdTarget('CHIP', pack, root / 'test.pdsc', 'chip.svd')


def test_saved_id_survives_relocation_and_archive_layout(tmp_path, monkeypatch):
    first = target_at(tmp_path / '_MEIfirst')
    second = target_at(tmp_path / '_MEIsecond')
    assert first.key == second.key
    assert first.legacy_key != second.legacy_key
    assert SvdTarget(first.target, first.pack, tmp_path/'other.pack', first.svd, True).key == first.key
    assert target_at(tmp_path/'v2', 'Vendor.DFP@2').key != first.key
    monkeypatch.setattr('mklink.peripheral_watch.discover_svd_targets', lambda root: [first])
    save_catalog_selection(tmp_path, load_catalog(tmp_path, target_id=first.key))
    monkeypatch.setattr('mklink.peripheral_watch.discover_svd_targets', lambda root: [second])
    assert load_catalog(tmp_path).selection['id'] == second.key


def test_legacy_id_requires_exact_original_source_and_does_not_guess_chip(tmp_path, monkeypatch):
    first = target_at(tmp_path/'first')
    second = target_at(tmp_path/'second')
    monkeypatch.setattr('mklink.peripheral_watch.discover_svd_targets', lambda root: [first])
    assert load_catalog(tmp_path, target_id=first.legacy_key).selection['id'] == first.key
    monkeypatch.setattr('mklink.peripheral_watch.discover_svd_targets', lambda root: [second])
    with pytest.raises(ValueError, match='unavailable or ambiguous'):
        load_catalog(tmp_path, target_id=first.legacy_key)
    with pytest.raises(ValueError):
        load_catalog(tmp_path, target_id='missing')
    monkeypatch.setattr('mklink.peripheral_watch.discover_svd_targets', lambda root: [first, second])
    with pytest.raises(ValueError, match='ambiguous'):
        load_catalog(tmp_path, target_id=first.key)


@pytest.mark.parametrize('saved', ['{broken', '{"target_id":"expired"}', '{"svd":"missing.svd"}', '{"chip":"CHIP"}'])
def test_invalid_restore_is_visible_and_explicit_selection_repairs_it(tmp_path, monkeypatch, saved):
    target = target_at(tmp_path)
    monkeypatch.setattr('mklink.peripheral_watch.discover_svd_targets', lambda root: [target])
    path = tmp_path/'.mklink/peripheral-selection.json'
    path.parent.mkdir()
    path.write_text(saved)
    device = SimpleNamespace(_project_root=str(tmp_path), symbol_catalog=None)
    manager = SuperWatchStreamManager()
    manager.prepare(device)
    assert manager._device is device
    catalog = manager.peripheral_catalog()
    assert catalog['restore_error']
    assert catalog['items'] == [] and catalog['selection'] is None
    assert path.read_text() == saved
    repaired = manager.select_peripherals(device, target_id=target.key)
    assert repaired['items'] and repaired['restore_error'] is None
    assert json.loads(path.read_text()) == {'target_id': target.key}


def test_reconnect_drops_old_peripheral_watches_but_preserves_ram(tmp_path, monkeypatch):
    target = target_at(tmp_path/'first')
    second = tmp_path/'second'
    (second/'.mklink').mkdir(parents=True)
    (second/'.mklink/peripheral-selection.json').write_text('{"target_id":"expired"}')
    monkeypatch.setattr('mklink.peripheral_watch.discover_svd_targets', lambda root: [target])
    manager = SuperWatchStreamManager()
    device = SimpleNamespace(_project_root=str(target.source.parent), symbol_catalog=None)
    manager.select_peripherals(device, target_id=target.key)
    ram = WatchItem('counter', 0x20000000, 'uint32_t', 4)
    manager._runtime.items.append(ram)
    assert 'error' not in manager.add_watch('GPIOB.12').get('item', {})
    manager.prepare(SimpleNamespace(_project_root=str(second), symbol_catalog=None))
    assert [item.name for item in manager._runtime.items] == ['counter']
    assert manager._runtime.svd_registers == {}
    assert manager.peripheral_catalog()['restore_error']
    assert manager.peripheral_catalog()['selection'] is None
