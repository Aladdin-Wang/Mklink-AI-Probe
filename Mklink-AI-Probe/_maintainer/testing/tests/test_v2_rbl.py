import hashlib
import io
import json
import struct
import zlib
from types import SimpleNamespace

import pytest

from mklink import firmware_check as fc
from mklink.rbl import PAYLOAD_LIMIT, validate_rbl


def rbl(*, version=b'V2.9.0', partition=b'MicroLink', algorithm=0, data=b'\x13\0\0\0' * 8, size=None):
    size = len(data) if size is None else size
    head = struct.pack('<4sHHI16s24s24sIIII', b'RBL\0', algorithm, 0, 0,
                       partition, version, b'', zlib.crc32(data), 0, size, size)
    return head + struct.pack('<I', zlib.crc32(head)) + data


@pytest.mark.parametrize('name,valid', [('MicroLink_V2.9.0.rbl', True), ('MicroLink_V2.9.0.uf2', False),
    ('MicroLink_V3.6.5.rbl', False), ('HPMLink_V2.9.0.rbl', False), ('HPMLink_V4.6.8.uf2', True)])
def test_file_format_is_bound_to_model(name, valid):
    assert bool(fc.parse_firmware_filename(name)) is valid


@pytest.mark.parametrize('change', ['header_crc', 'payload_crc', 'truncated', 'trailing', 'oversize',
                                  'partition', 'algorithm', 'version', 'unaligned'])
def test_rbl_rejects_wrong_or_damaged_images(tmp_path, change):
    data = bytearray(rbl())
    if change == 'header_crc': data[9] ^= 1
    elif change == 'payload_crc': data[-1] ^= 1
    elif change == 'truncated': data = data[:-4]
    elif change == 'trailing': data += b'1234'
    elif change == 'oversize': data = rbl(data=b'\0' * (PAYLOAD_LIMIT+4))
    elif change == 'partition': data = rbl(partition=b'bootloader')
    elif change == 'algorithm': data = rbl(algorithm=1)
    elif change == 'version': data = rbl(version=b'V3.9.0')
    elif change == 'unaligned': data = rbl(data=b'123')
    file = tmp_path/'bad.rbl'; file.write_bytes(data)
    with pytest.raises(ValueError): validate_rbl(file, version='V2.9.0')


def test_valid_rbl_header_and_named_version(tmp_path):
    file = tmp_path/'MicroLink_V2.9.0.rbl'; file.write_bytes(rbl())
    assert validate_rbl(file, version='V2.9.0') == 32
    with pytest.raises(ValueError): validate_rbl(file, version='V2.9.1')
    info = fc.parse_firmware_filename(file)
    assert fc._materialize_firmware(info) == (file, False, 'local')


def manifest(name, data):
    info = fc.parse_firmware_filename(name)
    return {'schema': fc.FIRMWARE_MANIFEST_SCHEMA, 'firmwares': [dict(
        name=name, model=info.model, family=info.family, version=info.version_str,
        size=len(data), sha256=hashlib.sha256(data).hexdigest(), urls={'github': 'https://example.test/'+name})]}


def test_v2_download_uses_separate_index_and_rbl_temp_suffix(monkeypatch):
    payload = manifest('MicroLink_V2.9.0.rbl', rbl())
    urls = []
    def get(request, timeout):
        urls.append(request.full_url)
        return io.BytesIO(rbl() if request.full_url.endswith('.rbl') else json.dumps(payload).encode())
    monkeypatch.setattr(fc, 'urlopen', get)
    info = fc._remote_firmware('V2')
    assert all(url.endswith('/latest-v2.json') for url in urls)
    path, owned, source = fc._materialize_firmware(info)
    try:
        assert owned and path.suffix == '.rbl' and source == 'github'
        assert path.read_bytes() == rbl()
    finally: path.unlink()
    assert fc._remote_firmwares_from_source('github') is None  # wrong channel rejected


@pytest.fixture
def update(monkeypatch, tmp_path):
    disk = tmp_path/'disk'; disk.mkdir()
    (disk/'readme.txt').write_text('V2.8.0')
    file = tmp_path/'MicroLink_V2.9.0.rbl'; file.write_bytes(rbl())
    monkeypatch.setattr(fc, '_remote_firmware', lambda *a, **k: None)
    return disk, tmp_path, file


def test_v2_copy_no_uf2_command_and_version_verified(update):
    disk, root, file = update
    calls = []
    def copy(source, name, bound):
        assert source == file and bound == str(disk)
        calls.append(name)
        (disk/'readme.txt').write_text('V2.9.0')
    device = SimpleNamespace(copy_rbl=copy, enter_bootloader=lambda: pytest.fail('V2 entered UF2'))
    result = fc.upgrade_probe_firmware(device, root, confirm=True, disk_reader=lambda: str(disk), verify_timeout=.1)
    assert result['status'] == 'updated' and calls == [file.name]


@pytest.mark.parametrize('current', ['V2.9.0', 'V2.10.0'])
def test_same_or_newer_version_never_copies(update, current):
    disk, root, _ = update
    (disk/'readme.txt').write_text(current)
    result = fc.upgrade_probe_firmware(SimpleNamespace(copy_rbl=lambda *a: pytest.fail('unexpected write')),
        root, confirm=True, disk_reader=lambda: str(disk))
    assert result['status'] == 'up_to_date'


@pytest.mark.parametrize('failure', ['copy', 'timeout', 'corrupt'])
def test_no_replay_or_false_success(update, failure):
    disk, root, file = update
    calls = []
    def copy(*args):
        calls.append(1)
        if failure == 'copy': raise OSError('removed during write')
    if failure == 'corrupt': file.write_bytes(b'bad')
    result = fc.upgrade_probe_firmware(SimpleNamespace(copy_rbl=copy), root, confirm=True,
        disk_reader=lambda: str(disk), verify_timeout=.01)
    assert result['status'] == ('manual_required' if failure == 'corrupt' else 'copied_unverified')
    assert calls == ([] if failure == 'corrupt' else [1])


def test_v2_manual_path_never_recommends_uf2(update):
    disk, root, _ = update
    result = fc.upgrade_probe_firmware(None, root, confirm=True, disk_reader=lambda: str(disk))
    assert result['status'] == 'manual_required' and result['format'] == 'rbl'
    assert 'RBL' in result['message']


def test_publisher_rejects_mutable_versions_and_rollback(update):
    from _maintainer.firmware.publish_v2_firmware import make_manifest
    _, _, file = update
    old = make_manifest(file, None, 'https://example.test/firmware.rbl')
    assert old['firmwares'][0]['rbl_payload_bytes'] == 32
    file.write_bytes(rbl(data=b'5678'))
    with pytest.raises(ValueError, match='immutable'):
        make_manifest(file, old, 'https://example.test/firmware.rbl')
    earlier = file.with_name('MicroLink_V2.8.0.rbl')
    earlier.write_bytes(rbl(version=b'V2.8.0'))
    with pytest.raises(ValueError, match='rollback'):
        make_manifest(earlier, old, 'https://example.test/firmware.rbl')


def test_bound_copy_holds_resources_and_refuses_changed_volume(monkeypatch, tmp_path):
    from mklink.runtime_probe import upgrade_firmware
    from mklink.remote.resource_manager import ResourceManager
    selected = dict(probe_id='probe', port='COM9', identity_stable=True)
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: selected)
    disk = tmp_path/'disk'; disk.mkdir()
    file = tmp_path/'MicroLink_V2.9.0.rbl'; file.write_bytes(rbl())
    manager = ResourceManager()
    state = dict(shared_probe_id='probe', resource_manager=manager)
    roots = [str(disk)]
    monkeypatch.setattr('mklink.probe_volumes.FirmwareVolumes', lambda p:
        SimpleNamespace(find=lambda **kw: roots[0]))
    def upgrade(device, *a, **kw):
        roots[0] = 'another disk'
        with pytest.raises(RuntimeError, match='changed'):
            device.copy_rbl(file, file.name, str(disk))
        assert not list(disk.iterdir())
        roots[0] = str(disk)
        device.copy_rbl(file, file.name, str(disk))
        assert (disk/file.name).read_bytes() == file.read_bytes()
        with pytest.raises(RuntimeError, match='already'):
            device.copy_rbl(file, file.name, str(disk))
        return {'status': 'copied_unverified'}
    monkeypatch.setattr(fc, 'upgrade_probe_firmware', upgrade)
    assert upgrade_firmware(state, tmp_path)['status'] == 'copied_unverified'
    assert not manager.get_status()


def test_cli_and_mcp_use_guarded_upgrade_without_target_attachment(monkeypatch, capsys):
    import asyncio
    from fastmcp import Client
    from mklink import runtime, runtime_mcp, cli
    calls = []
    info = {'probe_id': 'chosen'}
    monkeypatch.setattr(runtime, 'selected_runtime', lambda probe: info if probe == 'chosen' else None)
    monkeypatch.setattr(runtime, 'ensure_runtime', lambda **kw: pytest.fail('Unexpected backend start'))
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', lambda **kw: pytest.fail('Unexpected target attachment'))
    def request(selected, method, path, payload=None, **kwargs):
        assert selected is info
        calls.append((method, path, payload))
        return {'status': 'up_to_date'}
    monkeypatch.setattr(runtime, 'request', request)
    with pytest.raises(ValueError, match='confirm'):
        runtime.probe_firmware('upgrade', probe='chosen')
    cli._cli_runtime(SimpleNamespace(runtime_command='firmware', action='upgrade', probe='chosen', confirm=True))
    assert json.loads(capsys.readouterr().out)['status'] == 'up_to_date'
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            assert (await mcp.call_tool('probe_firmware', {'probe': 'chosen'})).data['status'] == 'up_to_date'
            assert (await mcp.call_tool('probe_firmware', {'probe': 'chosen', 'action': 'upgrade'}, raise_on_error=False)).is_error
            assert (await mcp.call_tool('probe_firmware', {'probe': 'chosen', 'action': 'upgrade', 'confirm': True})).data['status'] == 'up_to_date'
    asyncio.run(scenario())
    assert calls == [('POST', '/api/probe/firmware-upgrade', True),
                     ('GET', '/api/probe/firmware-check', None),
                     ('POST', '/api/probe/firmware-upgrade', True)]


def test_bound_check_never_uses_another_probe_disk(monkeypatch, tmp_path):
    from mklink.runtime_probe import check_firmware
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: {'port': 'COM9'})
    monkeypatch.setattr('mklink.probe_volumes.FirmwareVolumes', lambda p:
        SimpleNamespace(identity=None, find=lambda: pytest.fail('Unbound disk used')))
    def check(port, root, *, version_reader, disk_reader):
        assert disk_reader() is None
        assert port == 'COM9'
        return 'checked'
    monkeypatch.setattr(fc, 'check_probe_firmware', check)
    assert check_firmware({'shared_probe_id': 'chosen'}, tmp_path) == 'checked'


def test_publisher_preserves_legacy_tree_and_never_force_pushes(update, monkeypatch):
    from _maintainer.firmware import publish_v2_firmware as pub
    _, _, file = update
    calls, saved = [], {}
    def snapshot(repo):
        return ('old-head', 'old-tree', 'legacy-blob', saved.get('document'))
    def api(path, method='GET', body=None):
        calls.append((path, method, body))
        if path == 'user': return {'login': 'Aladdin-Wang'}
        if method == 'GET': return {'assets': [{'name': file.name}]}
        if path.endswith('/git/blobs'):
            saved['document'] = json.loads(body['content'])
            return {'sha': 'new-blob'}
        if path.endswith('/git/trees'):
            assert body == {'base_tree': 'old-tree', 'tree': [
                {'path': 'latest-v2.json', 'mode': '100644', 'type': 'blob', 'sha': 'new-blob'}]}
            return {'sha': 'new-tree'}
        if path.endswith('/git/commits'):
            assert body['parents'] == ['old-head']
            return {'sha': 'new-head'}
        assert method == 'PATCH' and body == {'sha': 'new-head', 'force': False}
        return {}
    monkeypatch.setattr(pub, 'snapshot', snapshot)
    monkeypatch.setattr(pub, 'api', api)
    monkeypatch.setattr(pub, 'verify_public_asset', lambda **kw: None)
    monkeypatch.setattr(pub, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(saved['document']).encode()))
    monkeypatch.setattr(pub.subprocess, 'run', lambda *a, **kw: pytest.fail('Existing asset overwritten'))
    assert pub.publish(file, ['test/repo'], True)[0]['legacy_index_unchanged']


def test_v2_download_endpoint_returns_verified_rbl(update, monkeypatch):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app
    _, root, file = update
    monkeypatch.setattr(fc, 'latest_firmware', lambda model, *a, **kw: fc.parse_firmware_filename(file))
    with TestClient(create_app(auth_token=None, project_root=str(root))) as client:
        response = client.get('/api/probe/firmware-download?model=V2')
        assert response.status_code == 200 and response.content == file.read_bytes()
        assert response.headers['x-mklink-firmware-name'] == file.name
        assert client.get('/api/probe/firmware-download?model=V2&family=hpmlink').status_code == 400
