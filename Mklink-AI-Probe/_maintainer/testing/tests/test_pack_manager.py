import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

import mklink.cmsis_dap.pack_manager as pack_manager_module
import mklink.cmsis_dap.pack_worker as pack_worker_module
from mklink.cmsis_dap.errors import FlashError, FlashErrorCode
from mklink.cmsis_dap.pack_catalog import PackCatalog
from mklink.cmsis_dap.pack_manager import PackManager, SubprocessPackWorker
from mklink.cmsis_dap.pack_worker import ReportingCache, handle_request, run_protocol
from mklink.cmsis_dap.paths import PackPaths


class FakeWorker:
    def __init__(self):
        self.commands = []

    def run(self, command, payload, on_event):
        self.commands.append((command, payload))
        on_event({"type": "progress", "current": 1, "total": 2})
        return {
            "status": "installed",
            "pack_id": "GigaDevice.GD32F30x_DFP",
            "version": "3.0.2",
        }


def _pack_path(paths, vendor, pack, version):
    return pack_manager_module._canonical_pack_path(paths, vendor, pack, version)


def _transaction_result(path):
    return {
        "status": "installed",
        "pack_id": "Test.Pack",
        "version": "1.0.0",
        "pack_path": str(Path(path).resolve()),
    }


def test_install_downloads_selected_part_only(tmp_path):
    worker = FakeWorker()
    manager = PackManager(root=tmp_path, worker=worker)

    result = manager.install("GD32F303RC", lambda event: None)

    assert worker.commands == [("install", {"part_number": "GD32F303RC"})]
    assert result == {
        "status": "installed",
        "pack_id": "GigaDevice.GD32F30x_DFP",
        "version": "3.0.2",
    }


def test_cancel_removes_staging(tmp_path):
    staging = PackPaths(tmp_path).staging_dir
    staging.mkdir(parents=True)
    (staging / "partial.pack").write_bytes(b"partial")
    manager = PackManager(root=tmp_path, worker=FakeWorker())
    manager._phase = "worker"

    manager.cancel()

    assert not staging.exists()


def test_cancel_preserves_unknown_sibling_staging_directory(tmp_path):
    paths = PackPaths(tmp_path)
    active = paths.staging_dir / "active-job"
    sibling = paths.staging_dir / "other-job"
    active.mkdir(parents=True)
    sibling.mkdir()
    (active / "partial.pack").write_bytes(b"active")
    (sibling / "partial.pack").write_bytes(b"sibling")
    direct_partial = paths.staging_dir / "direct.partial"
    direct_partial.write_bytes(b"direct")

    class Worker(FakeWorker):
        active_staging_dir = active

    manager = PackManager(tmp_path, worker=Worker())
    manager._phase = "worker"
    manager.cancel()

    assert not active.exists()
    assert (sibling / "partial.pack").read_bytes() == b"sibling"
    assert direct_partial.read_bytes() == b"direct"


def test_cancel_without_known_job_removes_direct_partials_but_keeps_child(tmp_path):
    paths = PackPaths(tmp_path)
    sibling = paths.staging_dir / "unknown-job"
    sibling.mkdir(parents=True)
    (sibling / "keep.pack").write_bytes(b"keep")
    direct = paths.staging_dir / "partial.pack"
    direct.write_bytes(b"partial")

    manager = PackManager(tmp_path, worker=FakeWorker())
    manager._phase = "worker"
    manager.cancel()

    assert not direct.exists()
    assert (sibling / "keep.pack").read_bytes() == b"keep"


def test_install_trims_part_number_and_forwards_events(tmp_path):
    worker = FakeWorker()
    events = []

    PackManager(tmp_path, worker=worker).install("  GD32F303RC  ", events.append)

    assert worker.commands == [("install", {"part_number": "GD32F303RC"})]
    assert events == [{"type": "progress", "current": 1, "total": 2}]


@pytest.mark.parametrize("part_number", ["", "  ", None, 123])
def test_install_rejects_empty_or_non_string_part_number(tmp_path, part_number):
    worker = FakeWorker()

    with pytest.raises(ValueError, match="part number"):
        PackManager(tmp_path, worker=worker).install(part_number, lambda event: None)

    assert worker.commands == []


def test_install_with_pack_path_merges_state_and_updates_catalog(tmp_path):
    paths = PackPaths(tmp_path)
    paths.index_dir.mkdir(parents=True)
    paths.index_file.write_text(
        json.dumps(
            {
                "GD32F303RC": {
                    "from_pack": {
                        "vendor": "GigaDevice",
                        "pack": "GD32F30x_DFP",
                        "version": "3.0.2",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    paths.data_dir.mkdir()
    old_pack = paths.data_dir / "Old.Pack.1.0.0.pack"
    old_pack.write_bytes(b"old")
    paths.state_file.write_text(
        json.dumps({"installed": {"Old.Pack": {"1.0.0": str(old_pack.resolve())}}}),
        encoding="utf-8",
    )
    installed_pack = _pack_path(
        paths, "GigaDevice", "GD32F30x_DFP", "3.0.2"
    )
    installed_pack.parent.mkdir(parents=True)
    installed_pack.write_bytes(b"pack")

    class InstalledWorker(FakeWorker):
        def run(self, command, payload, on_event):
            result = super().run(command, payload, on_event)
            result["pack_path"] = str(installed_pack)
            return result

    PackManager(tmp_path, worker=InstalledWorker()).install("GD32F303RC", lambda event: None)

    state = json.loads(paths.state_file.read_text(encoding="utf-8"))
    assert state == {
        "installed": {
            "Old.Pack": {"1.0.0": str(old_pack.resolve())},
            "GigaDevice.GD32F30x_DFP": {
                "3.0.2": str(installed_pack.resolve()),
            },
        }
    }
    record = PackCatalog(paths, builtin_provider=lambda: []).search("GD32F303RC")[0]
    assert record.installed is True
    assert record.pack_path == str(installed_pack.resolve())
    assert not list(paths.root.glob("state.json.*.tmp"))


def test_result_without_pack_path_does_not_create_state(tmp_path):
    PackManager(tmp_path, worker=FakeWorker()).install("GD32F303RC", lambda event: None)

    assert not PackPaths(tmp_path).state_file.exists()


def test_failed_result_with_pack_path_does_not_register_state(tmp_path):
    paths = PackPaths(tmp_path)
    pack_path = paths.data_dir / "failed.pack"
    pack_path.parent.mkdir(parents=True)
    pack_path.write_bytes(b"pack")

    class FailedWorker(FakeWorker):
        def run(self, command, payload, on_event):
            return {
                "status": "failed",
                "pack_id": "Vendor.Pack",
                "version": "1.0.0",
                "pack_path": str(pack_path),
            }

    result = PackManager(tmp_path, worker=FailedWorker()).install(
        "DEVICE", lambda event: None
    )

    assert result["status"] == "failed"
    assert not paths.state_file.exists()


def test_corrupt_state_is_not_overwritten_by_install(tmp_path):
    paths = PackPaths(tmp_path)
    paths.root.mkdir(exist_ok=True)
    paths.state_file.write_text("{broken", encoding="utf-8")
    pack_path = _pack_path(paths, "GigaDevice", "GD32F30x_DFP", "3.0.2")
    pack_path.parent.mkdir(parents=True)
    pack_path.write_bytes(b"pack")

    class InstalledWorker(FakeWorker):
        def run(self, command, payload, on_event):
            result = super().run(command, payload, on_event)
            result["pack_path"] = str(pack_path)
            return result

    with pytest.raises(FlashError) as raised:
        PackManager(tmp_path, worker=InstalledWorker()).install(
            "GD32F303RC", lambda event: None
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert paths.state_file.read_text(encoding="utf-8") == "{broken"


def test_import_pack_uses_exact_resolved_path_and_registers_result(tmp_path):
    source = tmp_path / "incoming" / "Device.PACK"
    source.parent.mkdir()
    source.write_bytes(b"pack")
    worker = FakeWorker()

    result = PackManager(tmp_path, worker=worker).import_pack(source, lambda event: None)

    assert worker.commands == [("import", {"path": str(source.resolve())})]
    assert result["status"] == "installed"


@pytest.mark.parametrize("name", ["missing.pack", "not-a-pack.zip"])
def test_import_pack_rejects_missing_or_wrong_extension(tmp_path, name):
    path = tmp_path / name
    if name.endswith(".zip"):
        path.write_bytes(b"zip")
    worker = FakeWorker()

    with pytest.raises(ValueError, match="pack"):
        PackManager(tmp_path, worker=worker).import_pack(path, lambda event: None)

    assert worker.commands == []


def _write_installed_state(paths, installed):
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.state_file.write_text(json.dumps({"installed": installed}), encoding="utf-8")


def test_remove_deletes_exact_version_and_preserves_other_versions(tmp_path):
    paths = PackPaths(tmp_path)
    version_1 = _pack_path(paths, "Vendor", "Device_DFP", "1.0.0")
    version_2 = _pack_path(paths, "Vendor", "Device_DFP", "2.0.0")
    version_1.parent.mkdir(parents=True)
    version_2.parent.mkdir(parents=True)
    version_1.write_bytes(b"one")
    version_2.write_bytes(b"two")
    _write_installed_state(
        paths,
        {"Vendor.Device_DFP": {"1.0.0": str(version_1), "2.0.0": str(version_2)}},
    )

    PackManager(tmp_path, worker=FakeWorker()).remove(
        "Vendor", "Vendor.Device_DFP", "1.0.0"
    )

    assert not version_1.exists()
    assert version_2.read_bytes() == b"two"
    assert json.loads(paths.state_file.read_text(encoding="utf-8")) == {
        "installed": {"Vendor.Device_DFP": {"2.0.0": str(version_2)}}
    }


def test_remove_refuses_registered_path_outside_data_without_changing_state(tmp_path):
    paths = PackPaths(tmp_path / "root")
    outside = tmp_path / "outside.pack"
    outside.write_bytes(b"user")
    installed = {"Vendor.Device_DFP": {"1.0.0": str(outside)}}
    _write_installed_state(paths, installed)
    before = paths.state_file.read_bytes()

    with pytest.raises(FlashError) as raised:
        PackManager(paths.root, worker=FakeWorker()).remove(
            "Vendor", "Device_DFP", "1.0.0"
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert outside.read_bytes() == b"user"
    assert paths.state_file.read_bytes() == before


def test_remove_refuses_pack_in_use(tmp_path):
    paths = PackPaths(tmp_path)
    pack_path = _pack_path(paths, "Vendor", "Device_DFP", "1.0.0")
    pack_path.parent.mkdir(parents=True)
    pack_path.write_bytes(b"pack")
    _write_installed_state(
        paths, {"Vendor.Device_DFP": {"1.0.0": str(pack_path)}}
    )

    with pytest.raises(FlashError) as raised:
        PackManager(tmp_path, worker=FakeWorker()).remove(
            "Vendor", "Device_DFP", "1.0.0", in_use=lambda pack_id, version: True
        )

    assert raised.value.code is FlashErrorCode.PROBE_BUSY
    assert pack_path.exists()


def test_cancel_calls_active_worker_once_and_only_removes_staging(tmp_path):
    paths = PackPaths(tmp_path)
    for path in (paths.data_dir / "keep.pack", paths.index_file, paths.state_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep", encoding="utf-8")
    paths.staging_dir.mkdir()
    (paths.staging_dir / "partial.pack").write_bytes(b"partial")

    class CancellableWorker:
        def __init__(self):
            self.started = threading.Event()
            self.released = threading.Event()
            self.cancel_calls = 0

        def run(self, command, payload, on_event):
            self.started.set()
            self.released.wait(2)
            return {"status": "cancelled"}

        def cancel(self):
            self.cancel_calls += 1
            self.released.set()

    worker = CancellableWorker()
    manager = PackManager(tmp_path, worker=worker)
    errors = []

    def install():
        try:
            manager.install("GD32F303RC", lambda event: None)
        except FlashError as error:
            errors.append(error)

    thread = threading.Thread(target=install)
    thread.start()
    assert worker.started.wait(1)

    manager.cancel()
    thread.join(2)
    manager.cancel()

    assert not thread.is_alive()
    assert worker.cancel_calls == 1
    assert [error.code for error in errors] == [FlashErrorCode.USER_ABORT]
    assert not paths.staging_dir.exists()
    assert (paths.data_dir / "keep.pack").read_text(encoding="utf-8") == "keep"
    assert paths.index_file.read_text(encoding="utf-8") == "keep"
    assert paths.state_file.read_text(encoding="utf-8") == "keep"


def test_cancelled_invocation_cannot_register_late_success(tmp_path):
    paths = PackPaths(tmp_path)
    pack_path = paths.data_dir / "Vendor" / "Device_DFP" / "1.0.0.pack"
    pack_path.parent.mkdir(parents=True)
    pack_path.write_bytes(b"pack")

    class LateSuccessWorker:
        def __init__(self):
            self.started = threading.Event()
            self.released = threading.Event()

        def run(self, command, payload, on_event):
            self.started.set()
            self.released.wait(2)
            return {
                "status": "installed",
                "pack_id": "Vendor.Device_DFP",
                "version": "1.0.0",
                "pack_path": str(pack_path),
            }

        def cancel(self):
            self.released.set()

    worker = LateSuccessWorker()
    manager = PackManager(tmp_path, worker=worker)
    errors = []

    def install():
        try:
            manager.install("DEVICE", lambda event: None)
        except FlashError as error:
            errors.append(error)

    thread = threading.Thread(target=install)
    thread.start()
    assert worker.started.wait(1)
    manager.cancel()
    thread.join(2)

    assert [error.code for error in errors] == [FlashErrorCode.USER_ABORT]
    assert not paths.state_file.exists()


def test_reporting_cache_tick_emits_structured_current_and_total():
    events = []
    cache = object.__new__(ReportingCache)
    cache._event_emitter = events.append

    cache._verbose_on_tick_fn(12, 5)

    assert events == [{"type": "progress", "current": 5, "total": 12}]


def test_worker_install_downloads_only_pack_for_exact_selected_device(tmp_path):
    class PackRef:
        vendor = "GigaDevice"
        pack = "GD32F30x_DFP"
        version = "3.0.2"

        def get_pack_name(self):
            return str(Path(self.vendor) / self.pack / (self.version + ".pack"))

    class FakeCache:
        instances = []

        def __init__(self, silent, no_timeouts, json_path, data_path, emitter):
            self.silent = silent
            self.json_path = Path(json_path)
            self.data_path = Path(data_path)
            assert self.json_path.is_dir()
            assert self.data_path.is_dir()
            self.emitter = emitter
            self.selected_devices = None
            self.downloaded_refs = None
            self._index = {
                "GD32F303RC": {
                    "from_pack": {
                        "vendor": "GigaDevice",
                        "pack": "GD32F30x_DFP",
                        "version": "3.0.2",
                    }
                },
                "OTHER": {
                    "from_pack": {
                        "vendor": "Other",
                        "pack": "Other_DFP",
                        "version": "9.9.9",
                    }
                },
            }
            self.instances.append(self)

        def cache_descriptors(self):
            (self.json_path / "index.json").write_text(
                json.dumps(self._index), encoding="utf-8"
            )
            (self.json_path / "aliases.json").write_text("{}", encoding="utf-8")

        @property
        def index(self):
            return self._index

        def packs_for_devices(self, devices):
            self.selected_devices = devices
            return [PackRef()]

        def download_pack_list(self, refs):
            self.downloaded_refs = refs
            artifact = self.data_path / refs[0].get_pack_name()
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"downloaded")

    events = []
    result = handle_request(
        {
            "command": "install",
            "payload": {"part_number": "GD32F303RC"},
            "root": str(tmp_path),
            "staging_dir": str((PackPaths(tmp_path).staging_dir / "install-job").resolve()),
        },
        events.append,
        cache_factory=FakeCache,
    )

    cache = FakeCache.instances[0]
    assert events[0]["event"] == "staging"
    assert Path(events[0]["path"]).is_absolute()
    assert cache.silent is False
    assert cache.selected_devices == [cache.index["GD32F303RC"]]
    assert len(cache.downloaded_refs) == 1
    assert result["pack_id"] == "GigaDevice.GD32F30x_DFP"
    assert result["version"] == "3.0.2"
    pack_path = Path(result["pack_path"])
    assert pack_path.read_bytes() == b"downloaded"
    assert pack_path == _pack_path(
        PackPaths(tmp_path), "GigaDevice", "GD32F30x_DFP", "3.0.2"
    )
    parent = SubprocessPackWorker(PackPaths(tmp_path))
    parent._active_staging_dir = Path(events[0]["path"])
    parent.acknowledge_commit(result)
    assert not PackPaths(tmp_path).staging_dir.exists()


def test_worker_import_promotes_exact_artifact_and_metadata(tmp_path):
    source = tmp_path / "incoming.pack"
    source.write_bytes(b"imported")

    class FakeImportCache:
        instances = []

        def __init__(self, silent, no_timeouts, json_path, data_path, emitter):
            self.json_path = Path(json_path)
            self.data_path = Path(data_path)
            assert self.json_path.is_dir()
            assert self.data_path.is_dir()
            self.added_path = None
            self._index = {}
            self.instances.append(self)

        def add_pack_from_path(self, path):
            self.added_path = Path(path)
            assert self.added_path.read_bytes() == b"imported"
            details = {
                "from_pack": {
                    "vendor": "Vendor",
                    "pack": "Device_DFP",
                    "version": "1.2.3",
                }
            }
            self._index = {"DEVICE_A": details, "DEVICE_B": details}
            self.json_path.joinpath("index.json").write_text(
                json.dumps(self._index), encoding="utf-8"
            )
            self.json_path.joinpath("aliases.json").write_text("{}", encoding="utf-8")

        @property
        def index(self):
            return self._index

    result = handle_request(
        {
            "command": "import",
            "payload": {"path": str(source)},
            "root": str(tmp_path),
            "staging_dir": str((PackPaths(tmp_path).staging_dir / "import-job").resolve()),
        },
        lambda event: None,
        cache_factory=FakeImportCache,
    )

    assert result == {
        "status": "installed",
        "pack_id": "Vendor.Device_DFP",
        "version": "1.2.3",
        "pack_path": str(
            _pack_path(PackPaths(tmp_path), "Vendor", "Device_DFP", "1.2.3")
        ),
    }
    assert Path(result["pack_path"]).read_bytes() == b"imported"
    parent = SubprocessPackWorker(PackPaths(tmp_path))
    parent._active_staging_dir = PackPaths(tmp_path).staging_dir / "import-job"
    parent.acknowledge_commit(result)
    assert not PackPaths(tmp_path).staging_dir.exists()


def test_worker_protocol_stdout_contains_json_lines_only():
    from io import StringIO

    stdin = StringIO(json.dumps({"command": "fake"}) + "\n")
    stdout = StringIO()

    def fake_handler(request, emit):
        emit({"type": "log", "message": "working"})
        return {"status": "installed", "pack_id": "V.P", "version": "1"}

    exit_code = run_protocol(stdin, stdout, handler=fake_handler)

    lines = stdout.getvalue().splitlines()
    assert exit_code == 0
    assert [json.loads(line) for line in lines] == [
        {"type": "log", "message": "working"},
        {
            "type": "result",
            "result": {"status": "installed", "pack_id": "V.P", "version": "1"},
        },
    ]


def test_subprocess_worker_forwards_progress_before_process_wait(monkeypatch, tmp_path):
    events = []
    confirmed_staging = []

    class FakeInput:
        def __init__(self):
            self.value = ""
            self.flushed = False
            self.closed = False

        def write(self, value):
            self.value += value

        def flush(self):
            self.flushed = True

        def close(self):
            self.closed = True

    class FakeError:
        def __init__(self):
            self.drained = threading.Event()

        def read(self):
            self.drained.set()
            return "diagnostic only"

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeInput()
            self.stderr = FakeError()
            self.wait_called = False
            self.returncode = None
            self.stdout = self._stdout_lines()

        def _stdout_lines(self):
            staging = Path(json.loads(self.stdin.value)["staging_dir"])
            staging.mkdir(parents=True)
            confirmed_staging.append(staging)
            yield json.dumps(
                {"type": "event", "event": "staging", "path": str(staging)}
            ) + "\n"
            assert worker.active_staging_dir == staging.resolve()
            yield json.dumps(
                {"type": "progress", "current": 1, "total": 2}
            ) + "\n"
            assert events == [{"type": "progress", "current": 1, "total": 2}]
            assert self.wait_called is False
            yield json.dumps(
                {
                    "type": "result",
                    "result": {
                        "status": "installed",
                        "pack_id": "Vendor.Device_DFP",
                        "version": "1.2.3",
                        "pack_path": "unused.pack",
                    },
                }
            ) + "\n"

        def wait(self, timeout=None):
            self.wait_called = True
            self.returncode = 0
            return 0

    process = FakeProcess()
    monkeypatch.setattr(
        "mklink.cmsis_dap.pack_manager.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    worker = SubprocessPackWorker(PackPaths(tmp_path))
    result = worker.run(
        "install", {"part_number": "DEVICE"}, events.append
    )

    assert result["status"] == "installed"
    assert process.stdin.flushed is True
    assert process.stdin.closed is True
    assert process.stderr.drained.is_set()
    assert process.wait_called is True
    assert len(confirmed_staging) == 1
    assert not confirmed_staging[0].exists()
    request = json.loads(process.stdin.value)
    assert request["payload"] == {"part_number": "DEVICE"}


def test_subprocess_worker_stops_process_on_invalid_json(monkeypatch, tmp_path):
    class Input:
        def write(self, value):
            pass

        def flush(self):
            pass

        def close(self):
            pass

    class Error:
        def read(self):
            return "diagnostic"

    class Process:
        def __init__(self):
            self.stdin = Input()
            self.stdout = iter(["not-json\n"])
            self.stderr = Error()
            self.terminated = False
            self.waited = False
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 1

        def wait(self, timeout=None):
            self.waited = True
            return self.returncode

    process = Process()
    monkeypatch.setattr(
        "mklink.cmsis_dap.pack_manager.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    with pytest.raises(FlashError) as raised:
        SubprocessPackWorker(PackPaths(tmp_path)).run(
            "install", {"part_number": "DEVICE"}, lambda event: None
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert process.terminated is True
    assert process.waited is True


def test_subprocess_cancel_before_run_latches_without_spawning(monkeypatch, tmp_path):
    popen_calls = 0

    def forbidden_popen(*args, **kwargs):
        nonlocal popen_calls
        popen_calls += 1
        raise AssertionError("Popen must not run after a latched cancel")

    monkeypatch.setattr(
        "mklink.cmsis_dap.pack_manager.subprocess.Popen", forbidden_popen
    )
    worker = SubprocessPackWorker(PackPaths(tmp_path))

    worker.cancel()
    with pytest.raises(FlashError) as raised:
        worker.run("install", {"part_number": "DEVICE"}, lambda event: None)

    assert raised.value.code is FlashErrorCode.USER_ABORT
    assert popen_calls == 0


def test_cancel_during_popen_factory_never_allows_success(monkeypatch, tmp_path):
    factory_entered = threading.Event()
    release_factory = threading.Event()
    cancel_done = threading.Event()

    class Input:
        def write(self, value):
            pass

        def flush(self):
            pass

        def close(self):
            pass

    class Error:
        def read(self):
            return ""

    class Process:
        def __init__(self):
            self.stdin = Input()
            self.stderr = Error()
            self.returncode = None
            self.terminated = threading.Event()
            self.stdout = self._lines()

        def _lines(self):
            if not self.terminated.wait(0.2):
                yield json.dumps(
                    {
                        "type": "result",
                        "result": {
                            "status": "installed",
                            "pack_id": "Vendor.Pack",
                            "version": "1.0.0",
                            "pack_path": "must-not-succeed.pack",
                        },
                    }
                ) + "\n"

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 1
            self.terminated.set()

        def wait(self, timeout=None):
            return self.returncode if self.returncode is not None else 0

    process = Process()

    def blocked_popen(*args, **kwargs):
        factory_entered.set()
        assert release_factory.wait(1)
        return process

    monkeypatch.setattr(
        "mklink.cmsis_dap.pack_manager.subprocess.Popen", blocked_popen
    )
    worker = SubprocessPackWorker(PackPaths(tmp_path))
    results = []
    errors = []

    def run_worker():
        try:
            results.append(
                worker.run("install", {"part_number": "DEVICE"}, lambda event: None)
            )
        except FlashError as error:
            errors.append(error)

    run_thread = threading.Thread(target=run_worker)
    run_thread.start()
    assert factory_entered.wait(1)

    def cancel_worker():
        worker.cancel()
        cancel_done.set()

    cancel_thread = threading.Thread(target=cancel_worker)
    cancel_thread.start()
    cancel_done.wait(0.1)
    release_factory.set()
    run_thread.join(2)
    cancel_thread.join(2)

    assert not run_thread.is_alive()
    assert not cancel_thread.is_alive()
    assert results == []
    assert [error.code for error in errors] == [FlashErrorCode.USER_ABORT]
    assert process.terminated.is_set()


def test_cancel_before_first_output_cleans_parent_known_staging(
    monkeypatch, tmp_path
):
    paths = PackPaths(tmp_path)
    stage_created = threading.Event()

    class Input:
        def __init__(self, process):
            self.process = process
            self.value = ""

        def write(self, value):
            self.value += value

        def flush(self):
            pass

        def close(self):
            request = json.loads(self.value)
            self.process.request = request
            stage = Path(request["staging_dir"])
            stage.mkdir(parents=True)
            stage_created.set()

    class Error:
        def read(self):
            return ""

    class Process:
        def __init__(self):
            self.stdin = Input(self)
            self.stderr = Error()
            self.returncode = None
            self.terminated = threading.Event()
            self.stdout = self._lines()
            self.request = None

        def _lines(self):
            self.terminated.wait(1)
            return
            yield

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 1
            self.terminated.set()

        def wait(self, timeout=None):
            return self.returncode

    process = Process()
    worker = SubprocessPackWorker(paths)
    observed_before_spawn = []

    def fake_popen(*args, **kwargs):
        observed_before_spawn.append(worker._active_staging_dir)
        return process

    monkeypatch.setattr(
        "mklink.cmsis_dap.pack_manager.subprocess.Popen", fake_popen
    )
    errors = []

    def run_worker():
        try:
            worker.run("install", {"part_number": "DEVICE"}, lambda event: None)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run_worker)
    thread.start()
    assert stage_created.wait(1)
    active = worker.active_staging_dir
    assert active is not None
    sibling = paths.staging_dir / "sibling"
    sibling.mkdir()
    (sibling / "keep").write_bytes(b"keep")

    worker.cancel()
    thread.join(2)

    assert observed_before_spawn == [active]
    assert not active.exists()
    assert (sibling / "keep").read_bytes() == b"keep"
    assert [error.code for error in errors if isinstance(error, FlashError)] == [
        FlashErrorCode.USER_ABORT
    ]


def test_child_uses_exact_parent_supplied_staging_directory(tmp_path):
    paths = PackPaths(tmp_path)
    supplied = paths.staging_dir / "parent-job"
    events = []

    with pytest.raises(pack_worker_module.WorkerFailure):
        handle_request(
            {
                "command": "unknown",
                "payload": {},
                "root": str(tmp_path),
                "staging_dir": str(supplied.resolve()),
            },
            events.append,
        )

    assert Path(events[0]["path"]) == supplied.resolve()
    assert not supplied.exists()


@pytest.mark.parametrize("fail_at", [2, 3, 5])
def test_transaction_replace_failure_restores_all_last_good_files(
    tmp_path, fail_at
):
    paths = PackPaths(tmp_path)
    targets = [
        _pack_path(paths, "Vendor", "Pack", "1.0.0"),
        paths.index_file,
        paths.aliases_file,
    ]
    old_values = [b"old-pack", b'{"old":"index"}', b'{"old":"aliases"}']
    new_values = [b"new-pack", b'{"new":"index"}', b'{"new":"aliases"}']
    stage = paths.staging_dir / "failure-job"
    stage.mkdir(parents=True)
    replacements = []
    for index, (target, old, new) in enumerate(zip(targets, old_values, new_values)):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(old)
        prepared = stage / "{}.prepared".format(index)
        prepared.write_bytes(new)
        replacements.append((prepared, target))

    calls = 0

    def failing_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("simulated replace failure")
        os.replace(source, destination)

    with pytest.raises(OSError, match="simulated"):
        pack_worker_module._commit_transaction(
            paths,
            replacements,
            stage,
            _transaction_result(targets[0]),
            replace=failing_replace,
        )

    assert [target.read_bytes() for target in targets] == old_values
    assert not list(paths.root.rglob("*.prepared"))
    assert not list(paths.root.rglob("*.backup"))
    assert not (paths.root / "pack-transaction.json").exists()


def test_recover_transaction_restores_interrupted_journal(tmp_path):
    paths = PackPaths(tmp_path)
    target = paths.data_dir / "Vendor" / "Pack" / "1.0.0.pack"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    stage = paths.staging_dir / "recovery-job"
    stage.mkdir(parents=True)
    prepared = stage / "prepared.pack"
    prepared.write_bytes(b"new")
    backup = stage / "target.backup"
    journal = paths.root / "pack-transaction.json"
    journal.write_text(
        json.dumps(
            {
                "phase": "committing",
                "staging_dir": str(stage.resolve()),
                "result": _transaction_result(target),
                "entries": [
                    {
                        "target": str(target.resolve()),
                        "prepared": str(prepared.resolve()),
                        "backup": str(backup.resolve()),
                        "original_exists": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    os.replace(target, backup)
    os.replace(prepared, target)

    pack_worker_module._recover_transaction(paths)

    assert target.read_bytes() == b"old"
    assert not prepared.exists()
    assert not backup.exists()
    assert not journal.exists()


def test_failed_rollback_keeps_journal_for_next_worker_recovery(tmp_path):
    paths = PackPaths(tmp_path)
    first = paths.data_dir / "first.pack"
    second = paths.index_file
    stage = paths.staging_dir / "rollback-job"
    stage.mkdir(parents=True)
    replacements = []
    for index, (target, old, new) in enumerate(
        (
            (first, b"old-first", b"new-first"),
            (second, b"old-second", b"new-second"),
        )
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(old)
        temporary = stage / "{}.prepared".format(index)
        temporary.write_bytes(new)
        replacements.append((temporary, target))

    calls = 0

    def unavailable_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError("replace unavailable")
        os.replace(source, destination)

    with pytest.raises(OSError, match="unavailable"):
        pack_worker_module._commit_transaction(
            paths,
            replacements,
            stage,
            _transaction_result(first),
            replace=unavailable_replace,
        )

    journal = paths.root / "pack-transaction.json"
    assert journal.is_file()

    pack_worker_module._recover_transaction(paths)

    assert first.read_bytes() == b"old-first"
    assert second.read_bytes() == b"old-second"
    assert not journal.exists()


def test_transaction_journal_write_failure_removes_prepared_files(
    monkeypatch, tmp_path
):
    paths = PackPaths(tmp_path)
    target = paths.data_dir / "target.pack"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    stage = paths.staging_dir / "journal-failure-job"
    stage.mkdir(parents=True)
    prepared = stage / "target.prepared"
    prepared.write_bytes(b"new")

    def fail_journal(path, value):
        raise OSError("journal unavailable")

    monkeypatch.setattr(
        pack_worker_module, "_write_transaction_journal", fail_journal
    )

    with pytest.raises(OSError, match="journal"):
        pack_worker_module._commit_transaction(
            paths, [(prepared, target)], stage, _transaction_result(target)
        )

    assert target.read_bytes() == b"old"
    assert not prepared.exists()
    assert not (paths.root / "pack-transaction.json").exists()


def test_prepared_files_exist_only_inside_unique_staging(tmp_path):
    paths = PackPaths(tmp_path)
    stage = paths.staging_dir / "known-job"
    stage_data = stage / "data"
    stage_index = stage / "index"
    stage_data.mkdir(parents=True)
    stage_index.mkdir()
    staged_pack = stage_data / "source.pack"
    staged_pack.write_bytes(b"new-pack")
    details = {
        "from_pack": {"vendor": "Vendor", "pack": "Pack", "version": "1.0.0"}
    }
    stage_index.joinpath("index.json").write_text(
        json.dumps({"DEVICE": details}), encoding="utf-8"
    )
    stage_index.joinpath("aliases.json").write_text("{}", encoding="utf-8")
    destination = _pack_path(paths, "Vendor", "Pack", "1.0.0")

    replacements = pack_worker_module._prepare_pack_transaction(
        staged_pack,
        stage_data,
        destination,
        stage_index,
        paths,
        ("Vendor", "Pack", "1.0.0"),
    )

    assert replacements
    assert all(
        stage.resolve() in Path(prepared).resolve().parents
        for prepared, _ in replacements
    )
    assert not list(paths.data_dir.rglob("*.prepared"))
    assert not list(paths.index_dir.rglob("*.prepared"))

    worker = SubprocessPackWorker(paths)
    worker._active_staging_dir = stage.resolve()
    worker._cleanup_active_staging()
    assert not stage.exists()


def test_parent_recovery_restores_committing_transaction_immediately(tmp_path):
    paths = PackPaths(tmp_path)
    stage = paths.staging_dir / "interrupted-job"
    stage.mkdir(parents=True)
    old_target = paths.data_dir / "old.pack"
    new_target = paths.index_file
    old_target.parent.mkdir(parents=True)
    new_target.parent.mkdir(parents=True)
    old_target.write_bytes(b"old-bytes")
    old_prepared = stage / "old.prepared"
    old_backup = stage / "old.backup"
    new_prepared = stage / "new.prepared"
    new_backup = stage / "new.backup"
    old_prepared.write_bytes(b"replacement")
    new_prepared.write_bytes(b"new-target")
    os.replace(old_target, old_backup)
    os.replace(old_prepared, old_target)
    os.replace(new_prepared, new_target)
    journal = paths.root / "pack-transaction.json"
    journal.write_text(
        json.dumps(
            {
                "phase": "committing",
                "staging_dir": str(stage.resolve()),
                "result": _transaction_result(old_target),
                "entries": [
                    {
                        "target": str(old_target.resolve()),
                        "prepared": str(old_prepared.resolve()),
                        "backup": str(old_backup.resolve()),
                        "original_exists": True,
                    },
                    {
                        "target": str(new_target.resolve()),
                        "prepared": str(new_prepared.resolve()),
                        "backup": str(new_backup.resolve()),
                        "original_exists": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    pack_worker_module.recover_pending_transaction(paths)

    assert old_target.read_bytes() == b"old-bytes"
    assert not new_target.exists()
    assert not old_backup.exists()
    assert not journal.exists()


def test_subprocess_cancel_recovers_before_cleaning_staging(
    monkeypatch, tmp_path
):
    paths = PackPaths(tmp_path)
    stage = paths.staging_dir / "cancel-job"
    stage.mkdir(parents=True)
    calls = []

    def recover(recovery_paths, **kwargs):
        calls.append(("recover", stage.exists(), recovery_paths.root))

    monkeypatch.setattr(
        pack_worker_module, "recover_pending_transaction", recover, raising=False
    )

    class Process:
        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def wait(self, timeout=None):
            return self.returncode

    worker = SubprocessPackWorker(paths)
    worker._active_staging_dir = stage.resolve()
    worker._process = Process()

    worker.cancel()

    assert calls == [("recover", True, paths.root)]
    assert not stage.exists()


def test_pack_manager_cancel_preserves_staging_on_recovery_integrity_error(
    tmp_path,
):
    paths = PackPaths(tmp_path)
    stage = paths.staging_dir / "diagnostic-job"
    stage.mkdir(parents=True)
    (stage / "evidence").write_bytes(b"keep")

    class CorruptRecoveryWorker(FakeWorker):
        active_staging_dir = stage

        def cancel(self):
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "corrupt transaction journal",
            )

    manager = PackManager(tmp_path, worker=CorruptRecoveryWorker())
    manager._active = True
    manager._phase = "worker"

    with pytest.raises(FlashError) as raised:
        manager.cancel()

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert (stage / "evidence").read_bytes() == b"keep"


def test_committed_result_wins_over_late_cancel(tmp_path):
    result = {
        "status": "installed",
        "pack_id": "Vendor.Pack",
        "version": "1.0.0",
        "pack_path": "committed.pack",
    }
    worker = SubprocessPackWorker(PackPaths(tmp_path))
    worker._committed_result = dict(result)
    worker._cancel_requested = True

    assert worker._finish_result("install", 1, None, "killed") == result
    assert worker._cancel_requested is False


def test_manager_acknowledges_state_or_rolls_back_on_state_failure(tmp_path):
    paths = PackPaths(tmp_path)
    pack_path = _pack_path(paths, "Vendor", "Pack", "1.0.0")
    pack_path.parent.mkdir(parents=True)
    pack_path.write_bytes(b"new")
    result = {
        "status": "installed",
        "pack_id": "Vendor.Pack",
        "version": "1.0.0",
        "pack_path": str(pack_path),
    }

    class HandshakeWorker(FakeWorker):
        def __init__(self):
            super().__init__()
            self.acked = []
            self.rolled_back = []

        def run(self, command, payload, on_event):
            return dict(result)

        def acknowledge_commit(self, value):
            self.acked.append(dict(value))

        def rollback_commit(self, value):
            self.rolled_back.append(dict(value))

    worker = HandshakeWorker()
    PackManager(tmp_path, worker=worker).install("DEVICE", lambda event: None)
    assert worker.acked == [result]
    assert worker.rolled_back == []

    paths.state_file.write_text("{broken", encoding="utf-8")
    failing_worker = HandshakeWorker()
    with pytest.raises(FlashError):
        PackManager(tmp_path, worker=failing_worker).install(
            "DEVICE", lambda event: None
        )
    assert failing_worker.acked == []
    assert failing_worker.rolled_back == [result]


@pytest.mark.parametrize("state_registered", [False, True])
def test_stale_committed_journal_rolls_back_unregistered_or_keeps_registered(
    tmp_path, state_registered
):
    paths = PackPaths(tmp_path)
    stage = paths.staging_dir / "committed-job"
    stage.mkdir(parents=True)
    target = _pack_path(paths, "Vendor", "Pack", "1.0.0")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new")
    backup = stage / "000.backup"
    backup.write_bytes(b"old")
    prepared = stage / "pack.prepared"
    result = {
        "status": "installed",
        "pack_id": "Vendor.Pack",
        "version": "1.0.0",
        "pack_path": str(target),
    }
    (paths.root / "pack-transaction.json").write_text(
        json.dumps(
            {
                "phase": "committed",
                "staging_dir": str(stage.resolve()),
                "result": result,
                "entries": [
                    {
                        "target": str(target),
                        "prepared": str(prepared),
                        "backup": str(backup),
                        "original_exists": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    if state_registered:
        _write_installed_state(
            paths, {"Vendor.Pack": {"1.0.0": str(target)}}
        )

    pack_worker_module.recover_pending_transaction(paths)

    assert target.read_bytes() == (b"new" if state_registered else b"old")
    assert not (paths.root / "pack-transaction.json").exists()


def test_cancelled_broken_pipe_is_user_abort_and_next_run_succeeds(
    monkeypatch, tmp_path
):
    write_entered = threading.Event()
    release_write = threading.Event()

    class Error:
        def read(self):
            return ""

    class BrokenInput:
        def write(self, value):
            write_entered.set()
            release_write.wait(1)
            raise BrokenPipeError("cancelled pipe")

        def flush(self):
            pass

        def close(self):
            pass

    class GoodInput:
        def write(self, value):
            pass

        def flush(self):
            pass

        def close(self):
            pass

    class Process:
        def __init__(self, broken):
            self.stdin = BrokenInput() if broken else GoodInput()
            self.stderr = Error()
            self.returncode = None
            self.broken = broken
            self.stdout = iter([]) if broken else iter([
                json.dumps({"type": "result", "result": {
                    "status": "installed", "pack_id": "Vendor.Pack",
                    "version": "1.0.0", "pack_path": "ok.pack",
                }}) + "\n"
            ])

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    processes = [Process(True), Process(False)]
    popen_calls = []

    def popen(*args, **kwargs):
        process = processes[len(popen_calls)]
        popen_calls.append(process)
        return process

    monkeypatch.setattr(
        "mklink.cmsis_dap.pack_manager.subprocess.Popen", popen
    )
    worker = SubprocessPackWorker(PackPaths(tmp_path))
    errors = []

    def first_run():
        try:
            worker.run("install", {"part_number": "ONE"}, lambda event: None)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=first_run)
    thread.start()
    assert write_entered.wait(1)
    worker.cancel()
    release_write.set()
    thread.join(2)

    assert len(errors) == 1
    assert isinstance(errors[0], FlashError)
    assert errors[0].code is FlashErrorCode.USER_ABORT
    result = worker.run("install", {"part_number": "TWO"}, lambda event: None)
    assert result["status"] == "installed"
    assert len(popen_calls) == 2


def test_manager_cancel_accepts_committed_result_then_registers_and_acks(tmp_path):
    paths = PackPaths(tmp_path)
    pack_path = _pack_path(paths, "Vendor", "Pack", "1.0.0")
    pack_path.parent.mkdir(parents=True)
    pack_path.write_bytes(b"new-pack")
    stage = paths.staging_dir / "committed-job"
    stage.mkdir(parents=True)
    backup = stage / "000.backup"
    backup.write_bytes(b"old-pack")
    result = {
        "status": "installed",
        "pack_id": "Vendor.Pack",
        "version": "1.0.0",
        "pack_path": str(pack_path),
    }

    class CoordinatedCommittedWorker:
        active_staging_dir = stage

        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()
            self.lock = threading.Lock()
            self._committed = None
            self.acked = []

        @property
        def committed_result(self):
            with self.lock:
                return dict(self._committed) if self._committed is not None else None

        def run(self, command, payload, on_event):
            self.started.set()
            assert self.release.wait(2)
            return dict(result)

        def cancel(self):
            with self.lock:
                self._committed = dict(result)
            self.release.set()

        def acknowledge_commit(self, value):
            state = json.loads(paths.state_file.read_text(encoding="utf-8"))
            assert state["installed"]["Vendor.Pack"]["1.0.0"] == str(pack_path)
            assert backup.read_bytes() == b"old-pack"
            self.acked.append(dict(value))
            backup.unlink()
            stage.rmdir()
            paths.staging_dir.rmdir()

    worker = CoordinatedCommittedWorker()
    manager = PackManager(tmp_path, worker=worker)
    results = []
    errors = []

    def install():
        try:
            results.append(manager.install("DEVICE", lambda event: None))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=install)
    thread.start()
    assert worker.started.wait(1)
    manager.cancel()
    thread.join(2)

    assert errors == []
    assert results == [result]
    assert worker.acked == [result]
    assert not paths.staging_dir.exists()


def test_late_cancel_during_registration_is_noop_and_next_install_succeeds(
    tmp_path,
):
    paths = PackPaths(tmp_path)
    pack_path = _pack_path(paths, "Vendor", "Pack", "1.0.0")
    pack_path.parent.mkdir(parents=True)
    pack_path.write_bytes(b"pack")
    result = {
        "status": "installed",
        "pack_id": "Vendor.Pack",
        "version": "1.0.0",
        "pack_path": str(pack_path),
    }

    class LatchingWorker:
        def __init__(self):
            self.lock = threading.Lock()
            self.stale_cancel = False
            self.cancel_calls = 0
            self.acks = 0

        def run(self, command, payload, on_event):
            with self.lock:
                if self.stale_cancel:
                    self.stale_cancel = False
                    raise FlashError(FlashErrorCode.USER_ABORT, "stale cancel")
            return dict(result)

        def cancel(self):
            with self.lock:
                self.cancel_calls += 1
                self.stale_cancel = True

        def acknowledge_commit(self, value):
            self.acks += 1

    worker = LatchingWorker()
    manager = PackManager(tmp_path, worker=worker)
    registration_entered = threading.Event()
    release_registration = threading.Event()
    original_write_state = manager._write_state

    def blocked_write_state(state):
        registration_entered.set()
        assert release_registration.wait(2)
        original_write_state(state)

    manager._write_state = blocked_write_state
    first_results = []
    first_errors = []

    def first_install():
        try:
            first_results.append(manager.install("DEVICE", lambda event: None))
        except BaseException as error:
            first_errors.append(error)

    thread = threading.Thread(target=first_install)
    thread.start()
    assert registration_entered.wait(1)
    manager.cancel()
    release_registration.set()
    thread.join(2)

    assert first_errors == []
    assert first_results == [result]
    assert worker.cancel_calls == 0
    assert worker.acks == 1

    second = manager.install("DEVICE", lambda event: None)
    assert second == result
    assert worker.acks == 2


def test_ack_consumes_worker_latch_from_process_end_transition(
    monkeypatch, tmp_path
):
    paths = PackPaths(tmp_path)
    target = _pack_path(paths, "Vendor", "Pack", "1.0.0")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"new")
    stage = paths.staging_dir / "transition-job"
    stage.mkdir(parents=True)
    backup = stage / "000.backup"
    backup.write_bytes(b"old")
    result = {
        "status": "installed",
        "pack_id": "Vendor.Pack",
        "version": "1.0.0",
        "pack_path": str(target),
    }
    (paths.root / "pack-transaction.json").write_text(
        json.dumps(
            {
                "phase": "committed",
                "staging_dir": str(stage),
                "result": result,
                "entries": [{
                    "target": str(target), "prepared": str(stage / "prepared"),
                    "backup": str(backup), "original_exists": True,
                }],
            }
        ),
        encoding="utf-8",
    )
    worker = SubprocessPackWorker(paths)
    worker._active_staging_dir = stage.resolve()
    process_ended = threading.Event()
    release_result = threading.Event()

    def first_run(command, payload, on_event):
        with worker._lock:
            worker._committed_result = dict(result)
        process_ended.set()
        assert release_result.wait(2)
        return dict(result)

    worker.run = first_run
    manager = PackManager(tmp_path, worker=worker)
    results = []

    thread = threading.Thread(
        target=lambda: results.append(manager.install("DEVICE", lambda event: None))
    )
    thread.start()
    assert process_ended.wait(1)
    manager.cancel()
    release_result.set()
    thread.join(2)

    assert results == [result]
    assert worker._cancel_requested is False

    class Stream:
        def write(self, value): pass
        def flush(self): pass
        def close(self): pass
        def read(self): return ""

    class Process:
        stdin = Stream()
        stderr = Stream()
        returncode = None
        stdout = iter([json.dumps({"type": "result", "result": result}) + "\n"])
        def wait(self, timeout=None): self.returncode = 0; return 0
        def poll(self): return self.returncode

    monkeypatch.setattr(
        "mklink.cmsis_dap.pack_manager.subprocess.Popen",
        lambda *args, **kwargs: Process(),
    )
    del worker.run
    assert worker.run("install", {"part_number": "NEXT"}, lambda event: None) == result


def _make_directory_link(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return
    except OSError:
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            pytest.skip("directory links unavailable: " + completed.stderr)


def test_remove_rejects_canonical_path_escaping_through_directory_link(tmp_path):
    paths = PackPaths(tmp_path / "managed")
    external = tmp_path / "external-vendor"
    external.mkdir()
    _make_directory_link(paths.data_dir / "Vendor", external)
    escaped = external / "Pack" / "1.0.0" / "Vendor.Pack.1.0.0.pack"
    escaped.parent.mkdir(parents=True)
    escaped.write_bytes(b"external")
    _write_installed_state(
        paths, {"Vendor.Pack": {"1.0.0": str(escaped.resolve())}}
    )
    state_before = paths.state_file.read_bytes()

    with pytest.raises(FlashError) as raised:
        PackManager(paths.root, worker=FakeWorker()).remove(
            "Vendor", "Pack", "1.0.0"
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert escaped.read_bytes() == b"external"
    assert paths.state_file.read_bytes() == state_before


def test_register_rejects_result_escaping_through_directory_link(tmp_path):
    paths = PackPaths(tmp_path / "managed")
    external = tmp_path / "external-vendor"
    external.mkdir()
    _make_directory_link(paths.data_dir / "Vendor", external)
    escaped = external / "Pack" / "1.0.0" / "Vendor.Pack.1.0.0.pack"
    escaped.parent.mkdir(parents=True)
    escaped.write_bytes(b"external")

    class EscapedWorker(FakeWorker):
        def run(self, command, payload, on_event):
            return {
                "status": "installed",
                "pack_id": "Vendor.Pack",
                "version": "1.0.0",
                "pack_path": str(escaped.resolve()),
            }

    with pytest.raises(FlashError) as raised:
        PackManager(paths.root, worker=EscapedWorker()).install(
            "DEVICE", lambda event: None
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert escaped.read_bytes() == b"external"
    assert not paths.state_file.exists()


def test_remove_rolls_pack_back_when_state_write_fails(tmp_path):
    paths = PackPaths(tmp_path)
    first = _pack_path(paths, "Vendor", "Pack", "1.0.0")
    second = _pack_path(paths, "Vendor", "Pack", "2.0.0")
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    _write_installed_state(
        paths,
        {"Vendor.Pack": {"1.0.0": str(first), "2.0.0": str(second)}},
    )
    state_before = paths.state_file.read_bytes()
    manager = PackManager(tmp_path, worker=FakeWorker())
    original_write_state = manager._write_state
    calls = 0

    def fail_once(state):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("disk full")
        original_write_state(state)

    manager._write_state = fail_once

    with pytest.raises(OSError, match="disk full"):
        manager.remove("Vendor", "Pack", "1.0.0")

    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert paths.state_file.read_bytes() == state_before
    assert not list(paths.root.rglob("*.backup"))
    assert not list(paths.root.rglob("*.tmp"))

    manager.remove("Vendor", "Pack", "1.0.0")

    assert not first.exists()
    assert second.read_bytes() == b"second"
    assert json.loads(paths.state_file.read_text(encoding="utf-8")) == {
        "installed": {"Vendor.Pack": {"2.0.0": str(second)}}
    }


def test_worker_validates_all_metadata_before_touching_last_good(tmp_path):
    paths = PackPaths(tmp_path)
    old_pack = _pack_path(paths, "Vendor", "Pack", "1.0.0")
    old_pack.parent.mkdir(parents=True)
    old_pack.write_bytes(b"old-pack")
    paths.index_dir.mkdir()
    paths.index_file.write_bytes(b'{"old":"index"}')
    paths.aliases_file.write_bytes(b'{"old":"aliases"}')

    class PackRef:
        vendor = "Vendor"
        pack = "Pack"
        version = "1.0.0"

        def get_pack_name(self):
            return str(Path("Vendor") / "Pack" / "1.0.0.pack")

    class MissingAliasesCache:
        def __init__(self, silent, no_timeouts, json_path, data_path, emitter):
            self.json_path = Path(json_path)
            self.data_path = Path(data_path)
            self._index = {
                "DEVICE": {
                    "from_pack": {
                        "vendor": "Vendor",
                        "pack": "Pack",
                        "version": "1.0.0",
                    }
                }
            }

        def cache_descriptors(self):
            self.json_path.joinpath("index.json").write_text(
                json.dumps(self._index), encoding="utf-8"
            )

        @property
        def index(self):
            return self._index

        def packs_for_devices(self, devices):
            return [PackRef()]

        def download_pack_list(self, refs):
            staged = self.data_path / refs[0].get_pack_name()
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"new-pack")

    with pytest.raises(pack_worker_module.WorkerFailure):
        handle_request(
            {
                "command": "install",
                "payload": {"part_number": "DEVICE"},
                "root": str(tmp_path),
                "staging_dir": str((paths.staging_dir / "validation-job").resolve()),
            },
            lambda event: None,
            cache_factory=MissingAliasesCache,
        )

    assert old_pack.read_bytes() == b"old-pack"
    assert paths.index_file.read_bytes() == b'{"old":"index"}'
    assert paths.aliases_file.read_bytes() == b'{"old":"aliases"}'
    assert not (paths.root / "pack-transaction.json").exists()


def test_canonical_pack_path_uses_identity_layout_without_duplicate_vendor(tmp_path):
    paths = PackPaths(tmp_path)

    result = pack_manager_module._canonical_pack_path(
        paths, "Vendor", "Vendor.Device_DFP", "1.2.3"
    )

    assert result == (
        paths.data_dir
        / "Vendor"
        / "Device_DFP"
        / "1.2.3"
        / "Vendor.Device_DFP.1.2.3.pack"
    ).resolve()


@pytest.mark.parametrize(
    "vendor,pack,version",
    [
        ("", "Pack", "1.0.0"),
        (".", "Pack", "1.0.0"),
        ("Vendor", "..", "1.0.0"),
        ("Vendor/escape", "Pack", "1.0.0"),
        ("Vendor", "Pack\\escape", "1.0.0"),
        ("Vendor", "Pack", "C:\\escape"),
    ],
)
def test_canonical_pack_path_rejects_unsafe_identity_segments(
    tmp_path, vendor, pack, version
):
    with pytest.raises(ValueError):
        pack_manager_module._canonical_pack_path(
            PackPaths(tmp_path), vendor, pack, version
        )


def test_manager_rejects_result_path_for_another_in_tree_pack(tmp_path):
    paths = PackPaths(tmp_path)
    wrong = (
        paths.data_dir
        / "Vendor"
        / "Other"
        / "1.0.0"
        / "Vendor.Other.1.0.0.pack"
    )
    wrong.parent.mkdir(parents=True)
    wrong.write_bytes(b"unrelated")

    class WrongPathWorker(FakeWorker):
        def run(self, command, payload, on_event):
            return {
                "status": "installed",
                "pack_id": "Vendor.Pack",
                "version": "1.0.0",
                "pack_path": str(wrong),
            }

    with pytest.raises(FlashError) as raised:
        PackManager(tmp_path, worker=WrongPathWorker()).install(
            "DEVICE", lambda event: None
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert wrong.read_bytes() == b"unrelated"
    assert not paths.state_file.exists()


def test_remove_refuses_state_pointing_to_another_in_tree_pack(tmp_path):
    paths = PackPaths(tmp_path)
    expected = (
        paths.data_dir
        / "Vendor"
        / "Pack"
        / "1.0.0"
        / "Vendor.Pack.1.0.0.pack"
    )
    unrelated = (
        paths.data_dir
        / "Vendor"
        / "Other"
        / "1.0.0"
        / "Vendor.Other.1.0.0.pack"
    )
    expected.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    expected.write_bytes(b"expected")
    unrelated.write_bytes(b"unrelated")
    _write_installed_state(
        paths, {"Vendor.Pack": {"1.0.0": str(unrelated)}}
    )
    before = paths.state_file.read_bytes()

    with pytest.raises(FlashError) as raised:
        PackManager(tmp_path, worker=FakeWorker()).remove(
            "Vendor", "Pack", "1.0.0"
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert expected.read_bytes() == b"expected"
    assert unrelated.read_bytes() == b"unrelated"
    assert paths.state_file.read_bytes() == before


def test_remove_never_recursively_deletes_registered_version_directory(tmp_path):
    paths = PackPaths(tmp_path)
    version_dir = paths.data_dir / "Vendor" / "Pack" / "1.0.0"
    version_dir.mkdir(parents=True)
    arbitrary = version_dir / "user-file.txt"
    arbitrary.write_bytes(b"user")
    _write_installed_state(
        paths, {"Vendor.Pack": {"1.0.0": str(version_dir)}}
    )
    before = paths.state_file.read_bytes()

    with pytest.raises(FlashError) as raised:
        PackManager(tmp_path, worker=FakeWorker()).remove(
            "Vendor", "Pack", "1.0.0"
        )

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
    assert arbitrary.read_bytes() == b"user"
    assert paths.state_file.read_bytes() == before
