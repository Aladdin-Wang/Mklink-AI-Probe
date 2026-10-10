import hashlib
import json

import pytest

from _maintainer.release.desktop_assets import TARGETS, collect_desktop_assets, desktop_layout
from _maintainer.release.publish_update_release import build_latest_document


def builds(root):
    updates, names = desktop_layout('0.3.2')
    paths = []
    for target, platforms in TARGETS.items():
        directory = root / target
        directory.mkdir()
        files = []
        for name in sorted(names):
            if f'-{target}.' not in name:
                continue
            payload = name.encode()
            (directory / name).write_bytes(payload)
            if not name.endswith('.sig'):
                files.append({'name': name, 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
        path = directory / 'build-manifest.json'
        path.write_text(json.dumps({'version': '0.3.2', 'source_commit': 'a' * 40,
            'target': target, 'files': files,
            'updater_platforms': {key: updates[key] for key in platforms}}))
        paths.append(path)
    return paths


def test_native_assets_preserve_installer_specific_update_payloads(tmp_path):
    paths = builds(tmp_path)
    sources, updates = collect_desktop_assets(paths, '0.3.2', 'a' * 40)
    assert {name for _, name in sources} == desktop_layout('0.3.2')[1]
    assert len(sources) == 10
    assert updates['linux-x86_64-deb'].endswith('.deb')
    assert updates['linux-x86_64-appimage'].endswith('.AppImage')
    assert updates['darwin-aarch64'].endswith('.app.tar.gz')


@pytest.mark.parametrize('damage', ['missing-target', 'duplicate-target', 'source', 'hash', 'missing-signature', 'empty-signature', 'path'])
def test_incomplete_or_mismatched_native_builds_are_rejected(tmp_path, damage):
    paths = builds(tmp_path)
    if damage == 'missing-target':
        paths.pop()
    elif damage == 'duplicate-target':
        paths.append(paths[0])
    elif damage in ('missing-signature', 'empty-signature'):
        signature = next(paths[0].parent.glob('*.sig'))
        signature.unlink() if damage == 'missing-signature' else signature.write_bytes(b'')
    else:
        data = json.loads(paths[0].read_text())
        if damage == 'source':
            data['source_commit'] = 'b' * 40
        elif damage == 'hash':
            data['files'][0]['sha256'] = '0' * 64
        else:
            data['files'][0]['name'] = '../../other.dmg'
        paths[0].write_text(json.dumps(data))
    with pytest.raises(ValueError):
        collect_desktop_assets(paths, '0.3.2', 'a' * 40)


def test_updater_document_cannot_replace_windows_or_omit_one_native_target():
    kwargs = dict(version='0.3.2', notes='fixes', published_at='2026-10-09T00:00:00Z',
        signature='win-signature', updater_url='https://example.com/setup.exe',
        updater_sha256='a' * 64, updater_size=12, skill_url='https://example.com/skill.zip',
        skill_sha256='b' * 64, skill_size=42, source_commit='c' * 40)
    platforms = {key: {'url': 'https://example.com/' + name, 'signature': 'native-signature'}
                 for key, name in desktop_layout('0.3.2')[0].items()}
    result = build_latest_document(**kwargs, desktop_platforms=platforms)
    assert len(result['platforms']) == 5
    assert result['platforms']['windows-x86_64']['signature'] == 'win-signature'
    platforms['windows-x86_64'] = {}
    with pytest.raises(ValueError):
        build_latest_document(**kwargs, desktop_platforms=platforms)
