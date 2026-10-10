"""Generate a portable-client configuration for this specific installation."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile


def configuration(cache_dir: str) -> dict:
    cache = Path(cache_dir).expanduser()
    if not cache.is_absolute():
        raise ValueError('MCP cache directory must be an absolute path')
    cache = cache.resolve()
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=cache) as test:
            test.write(b'mklink-cache-check')
            test.flush()
    except OSError as exc:
        raise ValueError(f'MCP cache directory is not writable: {cache}: {exc}') from exc
    executable = Path(sys.executable).absolute()
    if not executable.is_file():
        raise ValueError('Cannot locate the current Python/MKLink executable')
    frozen = getattr(sys, 'frozen', False)
    return {'mcpServers': {'mklink': {
        'command': str(executable),
        'args': ['mcp'] if frozen else ['-m', 'mklink', 'mcp'],
        # Resolve the same package even if the client starts in another folder.
        'cwd': str(cache if frozen else Path(__file__).resolve().parent.parent),
        'env': {'MKLINK_CACHE_DIR': str(cache), 'PYTHONUTF8': '1'},
    }}}
