import json
from pathlib import Path
import subprocess
import sys

import pytest

from mklink.mcp_config import configuration


def test_cli_emits_configuration_for_current_interpreter_and_writable_cache(tmp_path):
    cache = tmp_path / '缓存 with spaces'
    result = subprocess.run([sys.executable, '-m', 'mklink', 'mcp-config', '--cache-dir', str(cache)],
                            capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    server = json.loads(result.stdout)['mcpServers']['mklink']
    assert Path(server['command']) == Path(sys.executable).absolute()
    assert server['args'] == ['-m', 'mklink', 'mcp']
    assert Path(server['env']['MKLINK_CACHE_DIR']) == cache.resolve()
    assert cache.is_dir() and not list(cache.iterdir())
    assert (Path(server['cwd']) / 'mklink').is_dir()


@pytest.mark.parametrize('path_kind', ['relative', 'file', 'denied'])
def test_invalid_cache_is_actionable_and_does_not_emit_config(tmp_path, monkeypatch, path_kind):
    path = tmp_path / 'cache'
    if path_kind == 'relative':
        path = Path('relative-cache')
    elif path_kind == 'file':
        path.write_text('preserve', encoding='utf-8')
    else:
        def denied(**kw):
            raise PermissionError('AI account denied')
        monkeypatch.setattr('mklink.mcp_config.tempfile.TemporaryFile', denied)
    with pytest.raises(ValueError, match='absolute|not writable'):
        configuration(str(path))


def test_frozen_configuration_uses_bundled_entry_and_persistent_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    server = configuration(str(tmp_path))['mcpServers']['mklink']
    assert server['args'] == ['mcp']
    assert server['cwd'] == str(tmp_path.resolve())
