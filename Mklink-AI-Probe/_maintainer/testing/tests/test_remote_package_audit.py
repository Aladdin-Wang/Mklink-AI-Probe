"""PE instructions cannot be interpreted as path strings; data and markers stay audited."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.fixture
def builder():
    path = Path(__file__).resolve().parents[3] / 'packaging/site_agent/build.py'
    spec = importlib.util.spec_from_file_location('site_agent_audit_under_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_builtin_flm_allowlist_requires_complete_verified_manifest(builder, monkeypatch, tmp_path):
    from test_builtin_flm_assets import make_bundle
    assets = builder._builtin_flm_assets()
    monkeypatch.setattr(assets, 'EXPECTED_TARGET_COUNT', 1)
    monkeypatch.setattr(assets, 'EXPECTED_BLOB_COUNT', 1)
    monkeypatch.setattr(builder, '_builtin_flm_assets', lambda: assets)
    root = tmp_path / '_internal/mklink/builtin_flm'
    root.mkdir(parents=True)
    manifest = make_bundle(root)
    relative = '_internal/mklink/builtin_flm/' + manifest['blobs'][0]['file']
    allowed = builder._validated_builtin_flm_paths(tmp_path)
    assert allowed == {relative}
    builder._audit_name(relative, allowed_flm=allowed)
    for other in ('private.flm', '_internal/mklink/builtin_flm/private.flm', '../' + relative):
        with pytest.raises(RuntimeError):
            builder._audit_name(other, allowed_flm=allowed)
    (tmp_path / relative).write_bytes(b'changed')
    with pytest.raises(ValueError):
        builder._validated_builtin_flm_paths(tmp_path)


def test_builtin_flm_audit_rejects_unlisted_blob(builder, monkeypatch, tmp_path):
    from test_builtin_flm_assets import make_bundle
    assets = builder._builtin_flm_assets()
    monkeypatch.setattr(assets, 'EXPECTED_TARGET_COUNT', 1)
    monkeypatch.setattr(assets, 'EXPECTED_BLOB_COUNT', 1)
    monkeypatch.setattr(builder, '_builtin_flm_assets', lambda: assets)
    root = tmp_path / '_internal/mklink/builtin_flm'
    root.mkdir(parents=True)
    make_bundle(root)
    (root / 'blobs/unlisted.flm').write_bytes(b'unlisted')
    with pytest.raises(ValueError, match='unlisted'):
        builder._validated_builtin_flm_paths(tmp_path)


def test_verified_flm_only_exempts_nonallocated_debug_provenance(builder, monkeypatch):
    import elftools.elf.elffile
    class Section(dict):
        def __init__(self, name, flags, payload):
            super().__init__(sh_flags=flags)
            self.name, self.payload = name, payload
        def data(self): return self.payload
    debug = Section('.debug_info', 0, b'D:/vendor/source')
    data = Section('.data', 2, b'normal')
    monkeypatch.setattr(elftools.elf.elffile, 'ELFFile',
                        lambda stream: SimpleNamespace(iter_sections=lambda: iter([debug, data])))
    policy = {'markers': [b'current-private-root'], 'system_roots': []}
    builder._audit_content('FLM', b'ELF', policy, allow_builtin_flm_debug_paths=True)
    for payload in (b'current-private-root', b'-----BEGIN PRIVATE KEY-----'):
        with pytest.raises(RuntimeError):
            builder._audit_content('FLM', payload, policy, allow_builtin_flm_debug_paths=True)
    debug['sh_flags'] = 2
    with pytest.raises(RuntimeError, match='drive-local'):
        builder._audit_content('FLM', b'ELF', policy, allow_builtin_flm_debug_paths=True)
    debug['sh_flags'] = 0
    data.payload = b'file:///private/source'
    with pytest.raises(RuntimeError, match='local file URL'):
        builder._audit_content('FLM', b'ELF', policy, allow_builtin_flm_debug_paths=True)


def test_pe_audit_checks_data_sections_but_all_bytes_for_sensitive_markers(builder, monkeypatch):
    import pefile
    code = b'file:///H\x89'
    section_data = [b'ordinary data']
    sections = [SimpleNamespace(Characteristics=0x20000000, get_data=lambda: code),
                SimpleNamespace(Characteristics=0x40000000, get_data=lambda: section_data[0])]
    monkeypatch.setattr(pefile, 'PE', lambda **kwargs: SimpleNamespace(sections=sections, close=lambda: None))
    policy = {'markers': [b'private-build-root'], 'system_roots': []}
    builder._audit_content('native', code, policy, allow_pe_provenance_paths=True)
    with pytest.raises(RuntimeError, match='build-machine'):
        builder._audit_content('native', code+b'private-build-root', policy, allow_pe_provenance_paths=True)
    with pytest.raises(RuntimeError, match='credential'):
        builder._audit_content('native', code+b'-----BEGIN PRIVATE KEY-----', policy, allow_pe_provenance_paths=True)
    section_data[0] = b'file:///private/source\0'
    with pytest.raises(RuntimeError, match='local file URL'):
        builder._audit_content('native', code, policy, allow_pe_provenance_paths=True)
    # Ordinary files do not receive the native-code interpretation.
    with pytest.raises(RuntimeError, match='local file URL'):
        builder._audit_content('metadata', code, policy)


@pytest.mark.parametrize('location', ['body', 'name', 'comment'])
def test_svd_archive_audits_decompressed_paths(builder, location):
    import io, zipfile
    policy = {'markers': [], 'system_roots': []}
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('E:/private/device.svd' if location == 'name' else 'device.svd',
                         b'E:/private/source' if location == 'body' else b'<device/>')
        if location == 'comment': archive.comment = b'E:/private/comment'
    with pytest.raises(RuntimeError): builder._audit_svd_archive(data.getvalue(), policy)


def test_svd_archive_checks_members_and_sensitive_markers(builder):
    import io, zipfile
    policy = {'markers': [b'private-build-root'], 'system_roots': []}
    def blob(name, content):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name,content)
        return data.getvalue()
    builder._audit_svd_archive(blob('device.svd',b'<device/>'),policy)
    builder._audit_svd_archive(blob('device.xml',b'<device/>'),policy)
    for name,content in [('device.svd',b'private-build-root'),('payload.bin',b'x'),('../device.svd',b'x')]:
        with pytest.raises(RuntimeError): builder._audit_svd_archive(blob(name,content),policy)
