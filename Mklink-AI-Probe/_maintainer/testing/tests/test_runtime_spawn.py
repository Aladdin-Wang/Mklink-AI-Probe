"""Detached process storage must outlive a frozen desktop launcher."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from mklink import probes, runtime


def test_cold_runtime_can_publish_after_old_45_second_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr(probes, 'select_probe', lambda *a, **kw: {'probe_id': 'lobby'})
    clock = [0.0]
    spawned = []
    info = {'probe_id': 'lobby', 'port': 8766}
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(runtime.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(runtime, 'discover', lambda _: info if clock[0] >= 50 else None)
    def spawn(*args, **kwargs):
        spawned.append(args)
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    assert runtime.ensure_runtime(allow_lobby=True) == info
    assert len(spawned) == 1


@pytest.mark.parametrize("frozen", [False, True])
def test_runtime_spawn_does_not_depend_on_launchers_temporary_directory(tmp_path, monkeypatch, frozen):
    monkeypatch.setenv("MKLINK_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("TEMP", str(tmp_path / "launcher-temp"))
    monkeypatch.setattr(runtime.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(probes, "select_probe", lambda *args, **kwargs: {"probe_id": "lobby"})
    info = {"probe_id": "lobby", "port": 8765}
    spawned = []
    monkeypatch.setattr(runtime, "discover", lambda probe_id: info if spawned else None)

    def spawn(command, **kwargs):
        spawned.append((command, kwargs))
        return object()  # Discovery succeeds before process polling is needed.

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    assert runtime.ensure_runtime(project_root=str(tmp_path), allow_lobby=True) == info
    command, options = spawned[0]
    root = runtime._private_dir("lobby")
    assert Path(options["env"]["TEMP"]) == root / "tmp"
    assert Path(options["env"]["TMP"]) == root / "tmp"
    assert Path(options["env"]["TMPDIR"]) == root / "tmp"
    if frozen:
        assert Path(options["cwd"]) == root
        assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        assert "-m" not in command
    else:
        assert Path(options["cwd"]) == Path(runtime.__file__).resolve().parent.parent
        assert command[1:3] == ["-m", "mklink"]
