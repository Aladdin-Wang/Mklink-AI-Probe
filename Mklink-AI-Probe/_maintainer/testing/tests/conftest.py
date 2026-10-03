"""Keep advisory locks from unit tests out of the user's live port registry."""
import pytest


@pytest.fixture(autouse=True)
def isolated_port_lock_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path / 'port-locks'))
