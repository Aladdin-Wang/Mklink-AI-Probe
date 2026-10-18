"""Publish validated V2 RBL assets and latest-v2.json without touching legacy UF2.

Requires explicit maintainer publication authority. Default is a read-only plan.
Existing firmware branches/releases must exist. Ref updates are fast-forward;
concurrent publication fails instead of overwriting another maintainer's work.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mklink.firmware_check import _parse_manifest, FIRMWARE_MANIFEST_SCHEMA, parse_firmware_filename
from mklink.rbl import validate_rbl
from _maintainer.release.publish_update_release import verify_public_asset

INDEX = 'latest-v2.json'


def api(path, method='GET', body=None):
    args = ['gh', 'api', path, '--method', method]
    if body is not None:
        args += ['--input', '-']
    for attempt in range(3 if method == 'GET' else 1):
        try:
            return json.loads(subprocess.check_output(args, timeout=45,
                input=json.dumps(body).encode() if body is not None else None))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if method != 'GET' or attempt == 2:
                raise
            time.sleep(1)


def make_manifest(file, previous, url):
    info = parse_firmware_filename(file.name)
    if info is None or info.model != 'V2' or info.format != 'rbl':
        raise ValueError('Expected MicroLink_V2.x.y.rbl')
    payload = validate_rbl(file, version=info.version_str)
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    if previous is not None:
        old = _parse_manifest(previous)
        if len(old) != 1 or old[0].model != 'V2':
            raise ValueError('V2 index contains another model')
        if old[0].version > info.version:
            raise ValueError('Firmware rollback rejected')
        if old[0].version == info.version and (old[0].sha256 != digest or old[0].size != file.stat().st_size):
            raise ValueError('Same-version content is immutable')
    return {'schema': FIRMWARE_MANIFEST_SCHEMA,
            'published_at': datetime.now(timezone.utc).isoformat(),
            'firmwares': [dict(name=file.name, family='microlink', model='V2', format='rbl',
                version=info.version_str, size=file.stat().st_size, sha256=digest,
                rbl_payload_bytes=payload, urls={'github': url})]}


def snapshot(repo):
    base = f'repos/{repo}'
    head = api(base+'/git/ref/heads/firmware')['object']['sha']
    commit = api(base+'/git/commits/'+head)
    tree = api(base+'/git/trees/'+commit['tree']['sha'])['tree']
    legacy = next(row['sha'] for row in tree if row['path'] == 'latest.json')
    item = next((row for row in tree if row['path'] == INDEX), None)
    previous = None
    if item:
        blob = api(base+'/git/blobs/'+item['sha'])
        previous = json.loads(base64.b64decode(blob['content']))
    # Refuse a missing or redirected release; never create or retarget its tag.
    release = api(base+'/releases/tags/firmware-assets')
    if release['tag_name'] != 'firmware-assets':
        raise ValueError('Unexpected firmware release')
    return head, commit['tree']['sha'], legacy, previous


def publish(file, repos, apply=False):
    plans = []
    for repo in repos:
        head, tree, legacy, previous = snapshot(repo)
        url = f'https://github.com/{repo}/releases/download/firmware-assets/{file.name}'
        document = make_manifest(file, previous, url)
        plans.append((repo, head, tree, legacy, document))
    if not apply:
        return [{'repo': repo, 'index': INDEX, 'manifest': doc, 'published': False}
                for repo, _, _, _, doc in plans]
    if api('user')['login'] != 'Aladdin-Wang':
        raise RuntimeError('Firmware publication requires the maintainer account')
    # Validate all repositories before any upload; verify assets anonymously
    # before exposing any index. Existing assets are immutable.
    for repo, *_ in plans:
        release = api(f'repos/{repo}/releases/tags/firmware-assets')
        asset = next((a for a in release['assets'] if a['name'] == file.name), None)
        if asset is None:
            subprocess.run(['gh', 'release', 'upload', 'firmware-assets', str(file), '--repo', repo], check=True)
        verify_public_asset(url=f'https://github.com/{repo}/releases/download/firmware-assets/{file.name}',
                            expected_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                            expected_size=file.stat().st_size)
    results = []
    for repo, head, tree, legacy, doc in plans:
        base = f'repos/{repo}'
        blob = api(base+'/git/blobs', 'POST', {'content': json.dumps(doc, indent=2)+'\n', 'encoding': 'utf-8'})
        changed = api(base+'/git/trees', 'POST', {'base_tree': tree, 'tree': [
            {'path': INDEX, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']}]})
        commit = api(base+'/git/commits', 'POST', {'message': f'firmware: publish {file.name} on independent V2 index',
                    'tree': changed['sha'], 'parents': [head]})
        api(base+'/git/refs/heads/firmware', 'PATCH', {'sha': commit['sha'], 'force': False})
        after = snapshot(repo)
        if after[2] != legacy or after[3] != doc:
            raise RuntimeError('Published index verification failed')
        url = f'https://raw.githubusercontent.com/{repo}/firmware/{INDEX}'
        with urlopen(url, timeout=30) as response:
            if json.load(response) != doc:
                raise RuntimeError('Public V2 index is not yet confirmed; do not republish automatically')
        results.append({'repo': repo, 'index': INDEX, 'commit': commit['sha'], 'legacy_index_unchanged': True})
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('file', type=Path)
    p.add_argument('--repo', action='append', required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    print(json.dumps(publish(args.file, args.repo, args.apply), indent=2))
