import logging
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from mklink.runtime_logging import CHUNK_CHARS, runtime_diagnostics


def test_importing_flash_does_not_reconfigure_host_streams():
    result = subprocess.run([sys.executable, '-c', '''
import io, sys
output = io.StringIO()
sys.stdout = sys.stderr = output
import mklink.flash
assert sys.stdout is output and sys.stderr is output
'''], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_python_diagnostics_share_log_and_restore_streams_after_error(tmp_path):
    stdout, stderr = sys.stdout, sys.stderr
    previous_errors = logging.raiseExceptions
    with pytest.raises(ValueError, match='failure marker'):
        with runtime_diagnostics(tmp_path):
            print('stdout 中文')
            print('stderr 中文', file=sys.stderr)
            logger = logging.getLogger('runtime-diagnostic-test')
            handler = logging.StreamHandler()
            logger.addHandler(handler)
            try:
                logger.warning('logging 中文')
            finally:
                logger.removeHandler(handler)
            raise ValueError('failure marker')
    assert sys.stdout is stdout and sys.stderr is stderr
    assert logging.raiseExceptions == previous_errors
    log = (tmp_path / 'runtime.log').read_text(encoding='utf-8')
    assert all(text in log for text in ('stdout 中文', 'stderr 中文', 'logging 中文', 'ValueError: failure marker'))


def test_rotation_bounds_huge_unicode_print_and_existing_legacy_tail(tmp_path):
    limit = 4096
    path = tmp_path / 'runtime.log'
    path.write_bytes(b'old-' * limit * 8 + b'last-legacy-line\n')
    with runtime_diagnostics(tmp_path, max_bytes=limit, backup_count=2):
        assert path.stat().st_size <= limit
        print('界' * (limit * 20))
        print('latest record')
    files = list(tmp_path.glob('runtime.log*'))
    assert len(files) == 3
    # stdlib rollover counts text before UTF-8 encoding: overshoot is limited
    # to one small chunk, including when one write contains a huge string.
    assert all(p.stat().st_size <= limit + 6 * CHUNK_CHARS for p in files)
    assert path.read_text(encoding='utf-8').endswith('latest record\n')
    assert all('old-' not in p.read_text(encoding='utf-8') for p in files)


def test_concurrent_writers_and_separate_runtime_directories(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir(); second.mkdir()
    with runtime_diagnostics(first):
        stream = sys.stdout
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n: stream.write(f'row-{n}\n'), range(300)))
    with runtime_diagnostics(second):
        print('other runtime')
    assert sorted((first / 'runtime.log').read_text().splitlines()) == sorted(f'row-{n}' for n in range(300))
    assert (second / 'runtime.log').read_text() == 'other runtime\n'


def test_rollover_failure_does_not_recurse_or_abort_runtime(tmp_path, monkeypatch):
    from logging.handlers import RotatingFileHandler
    def unavailable(handler):
        raise OSError('disk unavailable')
    monkeypatch.setattr(RotatingFileHandler, 'doRollover', unavailable)
    with runtime_diagnostics(tmp_path, max_bytes=100):
        sys.stdout.write('seed\n')
        sys.stdout.write('x' * 200)
        sys.stdout.write('runtime stays alive\n')
    assert (tmp_path / 'runtime.log').read_text() == 'seed\nruntime stays alive\n'
