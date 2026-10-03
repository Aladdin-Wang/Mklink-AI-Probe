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


def test_native_handles_children_rotation_and_restore_in_real_process(tmp_path):
    result = subprocess.run([sys.executable, '-c', r'''
import os, sys, subprocess, threading
from pathlib import Path
from mklink.runtime_logging import runtime_diagnostics
root=Path(sys.argv[1])
original_inherit={fd:os.get_inheritable(fd) for fd in (1,2)}
with runtime_diagnostics(root, max_bytes=4096, backup_count=2):
    for _ in range(500):
        os.write(1, ('native-'+('界'*64)+'\n').encode())
    os.write(2,b'CRT-END\n')
    os.write(2,b'NATIVE-CRLF\r\n')
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetStdHandle.argtypes=[wintypes.DWORD]
        kernel.GetStdHandle.restype=wintypes.HANDLE
        kernel.WriteFile.argtypes=[wintypes.HANDLE,ctypes.c_char_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.LPVOID]
        kernel.WriteFile.restype=wintypes.BOOL
        for fd in (1,2):
            data=f'WIN32-{fd}\n'.encode()
            count=wintypes.DWORD()
            assert kernel.WriteFile(kernel.GetStdHandle(-10-fd),data,len(data),ctypes.byref(count),None)
            assert count.value==len(data)
    subprocess.run([sys.executable,'-c','import os; os.write(1,b"CHILD-OUT\\n"); os.write(2,b"CHILD-ERR\\n")'],check=True)
assert not any(t.name=='runtime-diagnostics' for t in threading.enumerate())
assert {fd:os.get_inheritable(fd) for fd in (1,2)}==original_inherit
files=list(root.glob('runtime.log*'))
assert len(files)==3
assert all(p.stat().st_size<=4096+6144 for p in files)
text=''.join(p.read_text(encoding='utf-8') for p in files)
assert all(b'\r\r\n' not in p.read_bytes() for p in files)
for marker in ['CRT-END','CHILD-OUT','CHILD-ERR']+(['WIN32-1','WIN32-2'] if os.name=='nt' else []):
    assert marker in text, marker
os.write(1,b'RESTORED-OUT\n')
os.write(2,b'RESTORED-ERR\n')
if os.name=='nt':
    for fd in (1,2):
        data=f'RESTORED-WIN32-{fd}\n'.encode()
        count=wintypes.DWORD()
        assert kernel.WriteFile(kernel.GetStdHandle(-10-fd),data,len(data),ctypes.byref(count),None)
''', str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    import os
    assert result.stdout == 'RESTORED-OUT\n' + ('RESTORED-WIN32-1\n' if os.name == 'nt' else '')
    assert result.stderr == 'RESTORED-ERR\n' + ('RESTORED-WIN32-2\n' if os.name == 'nt' else '')


@pytest.mark.parametrize('closed', ['1', '2', '1,2'])
def test_windowless_missing_descriptors_are_restored(tmp_path, closed):
    result = subprocess.run([sys.executable, '-c', r'''
import os,sys,threading
from pathlib import Path
from mklink.runtime_logging import runtime_diagnostics
closed=[int(n) for n in sys.argv[2].split(',')]
for fd in closed: os.close(fd)
sys.stdout=sys.stderr=None
with runtime_diagnostics(sys.argv[1]):
    print('windowless Python')
    os.write(1,b'windowless native\n')
for fd in closed:
    try: os.fstat(fd)
    except OSError: pass
    else: raise AssertionError('originally closed descriptor leaked')
assert not any(t.name=='runtime-diagnostics' for t in threading.enumerate())
text=(Path(sys.argv[1])/'runtime.log').read_text()
assert 'windowless Python' in text and 'windowless native' in text
''', str(tmp_path), closed], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_idle_child_cannot_hold_diagnostic_shutdown_open(tmp_path):
    result = subprocess.run([sys.executable, '-c', r'''
import sys,subprocess,time,threading
from mklink.runtime_logging import runtime_diagnostics
child=None
try:
    start=time.monotonic()
    with runtime_diagnostics(sys.argv[1]):
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
    assert child.poll() is None
    assert time.monotonic()-start<5
    assert not any(t.name=='runtime-diagnostics' for t in threading.enumerate())
finally:
    if child is not None:
        child.terminate()
        child.wait(timeout=5)
''', str(tmp_path)], capture_output=True, text=True, timeout=15)
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
