"""Both executable entries service the same Pack and guarded-child protocol."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from mklink.internal_process import dispatch_internal_process

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('entry', ['cli', 'remote'])
def test_pack_protocol_reaches_worker_in_both_entries(entry):
    command = ([sys.executable, '-m', 'mklink'] if entry == 'cli' else
               [sys.executable, str(ROOT/'packaging/site_agent/entry.py')])
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    result = subprocess.run(command+['--internal-pack-worker'], input='{}\n',
                            capture_output=True, text=True, env=env, cwd=ROOT, timeout=10)
    assert result.returncode == 1
    message = json.loads(result.stdout)
    assert message['type'] == 'error' and 'code' in message
    assert 'usage:' not in result.stderr


@pytest.mark.parametrize('entry', ['cli', 'remote'])
def test_guard_reaches_child_and_preserves_exit_code(entry):
    command = ([sys.executable, '-m', 'mklink'] if entry == 'cli' else
               [sys.executable, str(ROOT/'packaging/site_agent/entry.py')])
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    result = subprocess.run(command+['--internal-process-guard', str(os.getpid()),
                            sys.executable, '-c', 'raise SystemExit(7)'],
                            input='MKLINK-PROCESS-GUARD-GO\n', capture_output=True,
                            text=True, env=env, cwd=ROOT, timeout=10)
    assert result.returncode == 7
    assert result.stdout == 'MKLINK-PROCESS-GUARD-READY\n'


def test_normal_arguments_are_not_internal_and_guard_restores_argv():
    previous = sys.argv
    assert dispatch_internal_process(['start']) is None
    assert dispatch_internal_process(['--internal-pack-worker', 'unexpected']) is None
    assert dispatch_internal_process(['--internal-process-guard']) == 2
    assert sys.argv is previous
