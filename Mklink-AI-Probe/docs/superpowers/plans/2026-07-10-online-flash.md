# MKLink CMSIS-DAP Online Flash Implementation Plan

> **Historical completed plan.** Do not execute its task checklist or skill instructions. Use `docs/ai/CURRENT_HANDOFF.md` for current work.

**Goal:** Add a production-ready online programmer that only accepts MKLink CMSIS-DAP probes, searches the full CMSIS-Pack index, downloads the selected DFP on demand, and programs verified HEX or BIN images from a four-zone Vue workspace.

**Architecture:** Keep online flash in a focused `mklink.cmsis_dap` package and mount a small FastAPI router from the existing app. Blocking pyOCD and Pack Manager work runs outside the event loop; a single job manager owns session cleanup and the `target_debug` lease. The Vue route consumes REST for control and SSE for progress/log events.

**Tech Stack:** Python 3.9+, pyOCD 0.44.x, cmsis-pack-manager, IntelHex, FastAPI, Vue 3, TypeScript, Vitest, pytest, Tauri v2.

---

Run test, build, and Git commands from the inner project root unless a step explicitly changes directory:

```text
E:\software\HPM5300\Mklink-AI-Probe\Mklink-AI-Probe
```

## File map

### Python files to create

- `mklink/cmsis_dap/__init__.py` — public online-flash exports.
- `mklink/cmsis_dap/errors.py` — stable error codes and exception mapping.
- `mklink/cmsis_dap/models.py` — immutable domain records and enums.
- `mklink/cmsis_dap/paths.py` — user cache paths with environment override for tests.
- `mklink/cmsis_dap/pack_catalog.py` — built-in target and full index search.
- `mklink/cmsis_dap/pack_manager.py` — subprocess-owned index update/install/import/remove.
- `mklink/cmsis_dap/pack_worker.py` — isolated Pack Manager worker entry point.
- `mklink/cmsis_dap/probes.py` — MKLink-only CMSIS-DAP filtering.
- `mklink/cmsis_dap/images.py` — HEX/BIN inspection and paged preview.
- `mklink/cmsis_dap/backend.py` — pyOCD session operations.
- `mklink/cmsis_dap/jobs.py` — one-active-job state machine and event log.
- `mklink/remote/online_flash_api.py` — REST/SSE endpoints and request models.

### Python files to modify

- `pyproject.toml` — Python floor and GUI dependencies.
- `mklink/remote/api.py` — initialise online-flash services and include router.
- `mklink/remote/resource_manager.py` — add `TARGET_DEBUG`.
- `mklink/remote/dashboards.py` — acquire/release `TARGET_DEBUG` for target streams.
- `mklink/remote/api.py` — acquire/release `TARGET_DEBUG` around native target operations through the API service boundary.
- `dapflash.spec` does not belong to this repository and must not be copied.

### Python tests to create

- `_maintainer/testing/tests/test_online_flash_dependencies.py`
- `_maintainer/testing/tests/test_online_flash_errors.py`
- `_maintainer/testing/tests/test_pack_catalog.py`
- `_maintainer/testing/tests/test_pack_manager.py`
- `_maintainer/testing/tests/test_online_flash_probes.py`
- `_maintainer/testing/tests/test_online_flash_images.py`
- `_maintainer/testing/tests/test_online_flash_backend.py`
- `_maintainer/testing/tests/test_online_flash_jobs.py`
- `_maintainer/testing/tests/test_online_flash_api.py`

### Vue files to create

- `gui/src/views/OnlineFlashView.vue` — four-zone workspace.
- `gui/src/types/onlineFlash.ts` — API contracts.
- `gui/src/composables/useOnlineFlashApi.ts` — REST/SSE client.
- `gui/src/components/online-flash/ProbeSettingsPanel.vue`
- `gui/src/components/online-flash/TargetPackPanel.vue`
- `gui/src/components/online-flash/FirmwareWorkspace.vue`
- `gui/src/components/online-flash/FlashMapPanel.vue`
- `gui/src/components/online-flash/FlashActionBar.vue`
- `gui/src/components/online-flash/FlashLogPanel.vue`
- `gui/src/components/online-flash/HexPreview.vue`
- `gui/src/lib/hexPreview.ts` — row formatting and paging helpers.
- `gui/src/views/OnlineFlashView.test.ts`
- `gui/src/lib/hexPreview.test.ts`

### Vue files to modify

- `gui/src/router.ts` — add `/online-flash`.
- `gui/src/App.vue` — add top-level navigation.
- `gui/src/views/DashboardView.vue` — rename the current flash tab to “脱机烧录”.
- `gui/src/types/mklink.ts` — do not add online-flash types here; import the focused type module.

## Task 1: Pin runtime dependencies and Python compatibility

**Files:**
- Modify: `pyproject.toml`
- Create: `_maintainer/testing/tests/test_online_flash_dependencies.py`

- [ ] **Step 1: Write the dependency contract test**

```python
from importlib.metadata import version


def test_online_flash_dependencies_are_importable():
    import intelhex
    import pyocd
    import cmsis_pack_manager

    assert intelhex is not None
    assert pyocd.__version__ == version("pyocd")
    assert cmsis_pack_manager.Cache is not None
```

- [ ] **Step 2: Run the test and verify the project environment reports missing dependencies**

Run from the inner project root:

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_dependencies.py -q
```

Expected before dependency installation: FAIL with an import error for `pyocd` or `intelhex`.

- [ ] **Step 3: Update `pyproject.toml`**

Set:

```toml
[project]
requires-python = ">=3.9"

[project.optional-dependencies]
gui = [
  "fastapi>=0.100",
  "starlette>=0.40,<0.47",
  "uvicorn>=0.20",
  "websockets>=11.0",
  "pyocd>=0.44,<0.45",
  "intelhex>=2.3",
  "python-multipart>=0.0.9",
]
```

Keep existing `test`, `e2e`, `hil`, and `mcp` groups unchanged.

- [ ] **Step 4: Install the editable GUI/test environment and rerun**

```powershell
python -m pip install -e ".[gui,test]"
python -m pytest _maintainer/testing/tests/test_online_flash_dependencies.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml _maintainer/testing/tests/test_online_flash_dependencies.py
git commit -m "build: add online flash dependencies"
```

## Task 2: Define errors and immutable domain contracts

**Files:**
- Create: `mklink/cmsis_dap/__init__.py`
- Create: `mklink/cmsis_dap/errors.py`
- Create: `mklink/cmsis_dap/models.py`
- Create: `_maintainer/testing/tests/test_online_flash_errors.py`

- [ ] **Step 1: Write failing tests for error serialization and job transitions**

```python
import pytest

from mklink.cmsis_dap.errors import FlashError, FlashErrorCode
from mklink.cmsis_dap.models import JobState, assert_transition


def test_flash_error_serializes_stable_code():
    error = FlashError(FlashErrorCode.PACK_DOWNLOAD_FAIL, "network timeout")
    assert error.to_dict() == {
        "code": "PACK_DOWNLOAD_FAIL",
        "title": "Pack 下载失败",
        "message": "network timeout",
    }


def test_job_state_rejects_backward_transition():
    with pytest.raises(ValueError, match="programming -> connecting"):
        assert_transition(JobState.PROGRAMMING, JobState.CONNECTING)
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_errors.py -q
```

Expected: collection fails because `mklink.cmsis_dap` does not exist.

- [ ] **Step 3: Implement errors and state contracts**

`errors.py` must define a `str, Enum` with every code from design section 12 and a title map. `models.py` must define:

```python
class JobState(str, Enum):
    QUEUED = "queued"
    CONNECTING = "connecting"
    ERASING = "erasing"
    PROGRAMMING = "programming"
    VERIFYING = "verifying"
    RESETTING = "resetting"
    DISCONNECTING = "disconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ALLOWED_TRANSITIONS = {
    JobState.QUEUED: {JobState.CONNECTING, JobState.FAILED, JobState.STOPPED},
    JobState.CONNECTING: {JobState.ERASING, JobState.PROGRAMMING, JobState.VERIFYING, JobState.RESETTING, JobState.DISCONNECTING, JobState.FAILED, JobState.STOPPING},
    JobState.ERASING: {JobState.PROGRAMMING, JobState.RESETTING, JobState.DISCONNECTING, JobState.FAILED, JobState.STOPPING},
    JobState.PROGRAMMING: {JobState.VERIFYING, JobState.RESETTING, JobState.DISCONNECTING, JobState.FAILED, JobState.STOPPING},
    JobState.VERIFYING: {JobState.RESETTING, JobState.DISCONNECTING, JobState.FAILED, JobState.STOPPING},
    JobState.RESETTING: {JobState.DISCONNECTING, JobState.SUCCEEDED, JobState.FAILED, JobState.STOPPING},
    JobState.DISCONNECTING: {JobState.SUCCEEDED, JobState.STOPPED, JobState.FAILED},
    JobState.STOPPING: {JobState.DISCONNECTING, JobState.STOPPED, JobState.FAILED},
    JobState.STOPPED: set(),
    JobState.SUCCEEDED: set(),
    JobState.FAILED: set(),
}
```

Add frozen dataclasses for `ProbeRecord`, `TargetRecord`, `PackRecord`, `MemoryRegion`, `ImageSegment`, `ImageInspection`, `JobRequest`, `JobEvent`, and `JobSnapshot`. Use JSON-compatible primitive fields at API boundaries.

`JobRequest.full_sequence(image)` returns a request whose ordered actions are `connect`, `erase`, `program`, `verify`, `reset`, and `disconnect`. Single-action factories still include the required `connect`/`disconnect` boundary.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_errors.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
git add mklink/cmsis_dap _maintainer/testing/tests/test_online_flash_errors.py
git commit -m "feat: add online flash domain contracts"
```

## Task 3: Implement full PackCatalog search with cached-index fallback

**Files:**
- Create: `mklink/cmsis_dap/paths.py`
- Create: `mklink/cmsis_dap/pack_catalog.py`
- Create: `_maintainer/testing/tests/test_pack_catalog.py`

- [ ] **Step 1: Write catalog tests against a temporary index**

```python
import json

from mklink.cmsis_dap.pack_catalog import PackCatalog
from mklink.cmsis_dap.paths import PackPaths


def test_catalog_searches_case_insensitive_part_number(tmp_path):
    paths = PackPaths(root=tmp_path)
    paths.index_dir.mkdir(parents=True)
    paths.index_file.write_text(json.dumps({
        "GD32F303RC": {
            "name": "GD32F303RC",
            "from_pack": {"vendor": "GigaDevice", "pack": "GD32F30x_DFP", "version": "3.0.2"},
            "algorithms": [{"start": 0x08000000, "size": 0x40000, "file_name": "Flash/GD32F30x.FLM"}],
            "memories": {"IROM1": {"start": 0x08000000, "size": 0x40000}},
        }
    }), encoding="utf-8")

    results = PackCatalog(paths, builtin_provider=lambda: []).search("gd32f303")

    assert [item.part_number for item in results] == ["GD32F303RC"]
    assert results[0].installed is False


def test_catalog_keeps_last_good_index_when_refresh_fails(tmp_path):
    paths = PackPaths(root=tmp_path)
    paths.index_dir.mkdir(parents=True)
    paths.index_file.write_text(json.dumps({
        "STM32F103C8": {
            "name": "STM32F103C8",
            "from_pack": {"vendor": "Keil", "pack": "STM32F1xx_DFP", "version": "2.3.0"},
            "algorithms": [{"start": 0x08000000, "size": 0x10000, "file_name": "Flash/STM32F10x.FLM"}],
            "memories": {"IROM1": {"start": 0x08000000, "size": 0x10000}},
        }
    }), encoding="utf-8")
    catalog = PackCatalog(paths, builtin_provider=lambda: [])

    catalog.note_refresh_failure("offline")

    assert catalog.search("STM32F103C8")[0].part_number == "STM32F103C8"
    assert catalog.status().last_error == "offline"
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_pack_catalog.py -q
```

Expected: import failure for `PackCatalog`.

- [ ] **Step 3: Implement deterministic paths and search**

`PackPaths` must default to `%LOCALAPPDATA%\MKLink\pyocd`, support `MKLINK_PYOCD_HOME`, and expose `index_dir`, `index_file`, `aliases_file`, `data_dir`, `staging_dir`, and `state_file`.

`PackCatalog.search()` must:

```python
def search(self, query: str, vendor: str | None = None, installed: bool | None = None, limit: int = 100) -> list[TargetRecord]:
    needle = query.casefold().strip()
    records = self._combined_records()
    matches = [record for record in records if needle in record.part_number.casefold()]
    if vendor:
        matches = [record for record in matches if record.vendor.casefold() == vendor.casefold()]
    if installed is not None:
        matches = [record for record in matches if record.installed is installed]
    return sorted(matches, key=lambda record: (record.part_number.casefold(), record.pack_id or ""))[:limit]
```

Built-in targets come from a provider function so tests never import USB backends. Production provider reads `pyocd.target.TARGET` and marks source `builtin`.

- [ ] **Step 4: Run catalog tests**

```powershell
python -m pytest _maintainer/testing/tests/test_pack_catalog.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```powershell
git add mklink/cmsis_dap/paths.py mklink/cmsis_dap/pack_catalog.py _maintainer/testing/tests/test_pack_catalog.py
git commit -m "feat: add full CMSIS-Pack catalog"
```

## Task 4: Add cancellable on-demand Pack installation

**Files:**
- Create: `mklink/cmsis_dap/pack_manager.py`
- Create: `mklink/cmsis_dap/pack_worker.py`
- Create: `_maintainer/testing/tests/test_pack_manager.py`

- [ ] **Step 1: Write tests with a fake worker process**

```python
from mklink.cmsis_dap.pack_manager import PackManager


class FakeWorker:
    def __init__(self):
        self.commands = []

    def run(self, command, payload, on_event):
        self.commands.append((command, payload))
        on_event({"event": "progress", "current": 1, "total": 1})
        return {"status": "installed", "pack_id": "GigaDevice.GD32F30x_DFP", "version": "3.0.2"}


def test_install_uses_selected_part_only(tmp_path):
    worker = FakeWorker()
    manager = PackManager(root=tmp_path, worker=worker)

    result = manager.install("GD32F303RC", lambda event: None)

    assert result["status"] == "installed"
    assert worker.commands == [("install", {"part_number": "GD32F303RC"})]


def test_cancel_removes_staging_directory(tmp_path):
    manager = PackManager(root=tmp_path, worker=FakeWorker())
    manager.paths.staging_dir.mkdir(parents=True)
    (manager.paths.staging_dir / "partial.pack").write_bytes(b"partial")

    manager.cancel()

    assert not manager.paths.staging_dir.exists()
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_pack_manager.py -q
```

Expected: import failure for `PackManager`.

- [ ] **Step 3: Implement the worker boundary**

Use a subprocess because `cmsis_pack_manager.Cache` does not expose cooperative cancellation for its Rust download poller. `pack_worker.py` accepts JSON lines on stdin and emits JSON lines on stdout. The worker always operates on a unique staging cache. After success, atomically replace index metadata and promote the completed Pack version into the real cache. For production index update:

```python
cache = Cache(
    True,
    False,
    json_path=str(paths.index_dir),
    data_path=str(paths.data_dir),
)
cache.cache_descriptors()
```

Subclass `Cache` as `ReportingCache` and override `_verbose_on_tick_fn(total, current)` to emit structured progress. Construct it with `silent=False` so both descriptor and Pack downloads report progress without parsing human console text.

For a selected device:

```python
device = cache.index[part_number]
pack_refs = cache.packs_for_devices([device])
cache.download_pack_list(pack_refs)
```

`PackManager.cancel()` terminates the worker, waits up to five seconds, kills it if required, and removes only the staging directory. Never delete the last good index or installed Pack on cancellation.

- [ ] **Step 4: Add import and remove behavior**

Local import invokes `Cache.add_pack_from_path(path)`. Removal accepts exact `vendor`, `pack`, and `version`, refuses removal while an online job references that Pack, and deletes only the exact cached version directory.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest _maintainer/testing/tests/test_pack_manager.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```powershell
git add mklink/cmsis_dap/pack_manager.py mklink/cmsis_dap/pack_worker.py _maintainer/testing/tests/test_pack_manager.py
git commit -m "feat: install CMSIS-Packs on demand"
```

## Task 5: Filter MKLink probes and introduce target-debug arbitration

**Files:**
- Create: `mklink/cmsis_dap/probes.py`
- Modify: `mklink/remote/resource_manager.py`
- Modify: `mklink/remote/dashboards.py`
- Modify: `mklink/remote/api.py`
- Create: `_maintainer/testing/tests/test_online_flash_probes.py`
- Modify: `_maintainer/testing/tests/test_target_init.py`

- [ ] **Step 1: Write probe and resource tests**

```python
from types import SimpleNamespace

from mklink.cmsis_dap.probes import filter_mklink_probes
from mklink.remote.resource_manager import ResourceGroup, ResourceManager


def test_filter_rejects_non_mklink_cmsis_dap():
    probes = [
        SimpleNamespace(unique_id="mk-1", description="MicroKeen MKLink V4 CMSIS-DAP", vendor_name="MicroKeen", product_name="MKLink"),
        SimpleNamespace(unique_id="other-1", description="DAPLink CMSIS-DAP", vendor_name="ARM", product_name="DAPLink"),
    ]
    assert [probe.unique_id for probe in filter_mklink_probes(probes)] == ["mk-1"]


def test_target_debug_is_exclusive():
    manager = ResourceManager()
    manager.acquire(ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt")
    try:
        manager.acquire(ResourceGroup.TARGET_DEBUG, "user:online-flash:job-1")
    except Exception as error:
        assert error.conflict_owner == "user:dashboard:rtt"
    else:
        raise AssertionError("second target_debug lease unexpectedly succeeded")
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_probes.py -q
```

Expected: imports fail or `TARGET_DEBUG` is absent.

- [ ] **Step 3: Implement filtering**

Filter by a configurable VID/PID set first, then case-insensitive identity tokens `mklink`, `microlink`, `microkeen`. Return `ProbeRecord` values sorted by product and unique ID. Do not fall back to the first pyOCD probe.

- [ ] **Step 4: Add `ResourceGroup.TARGET_DEBUG` and dashboard ownership**

RTT, SystemView, VOFA, and SuperWatch start endpoints acquire `TARGET_DEBUG` together with `MKLINK_BRIDGE`; stop/failure paths release both under the same owner. Extend existing conflict-check responses so the online-flash page can identify active dashboard owners.

Wrap native API target operations (`flash`, `erase`, `reset`, `halt`, `resume`, memory, register, and variable access) in a small lease context manager in `api.py`. The context uses a stable `user:api:<operation>` owner and releases in `finally`; device methods remain unaware of the remote resource manager.

- [ ] **Step 5: Run focused and existing resource tests**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_probes.py _maintainer/testing/tests/test_target_init.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add mklink/cmsis_dap/probes.py mklink/remote/resource_manager.py mklink/remote/dashboards.py mklink/remote/api.py _maintainer/testing/tests/test_online_flash_probes.py _maintainer/testing/tests/test_target_init.py
git commit -m "feat: arbitrate MKLink CMSIS-DAP access"
```

## Task 6: Inspect HEX/BIN images and provide paged preview

**Files:**
- Create: `mklink/cmsis_dap/images.py`
- Create: `_maintainer/testing/tests/test_online_flash_images.py`

- [ ] **Step 1: Write failing HEX/BIN tests**

```python
from pathlib import Path

import pytest
from intelhex import IntelHex

from mklink.cmsis_dap.errors import FlashError, FlashErrorCode
from mklink.cmsis_dap.images import ImageInspector
from mklink.cmsis_dap.models import MemoryRegion


FLASH = MemoryRegion(name="flash", start=0x08000000, length=0x10000, is_flash=True)


def test_bin_requires_base_and_returns_preview(tmp_path: Path):
    path = tmp_path / "app.bin"
    path.write_bytes(bytes(range(32)))
    inspection = ImageInspector().inspect(path, [FLASH], base_address=0x08000000)
    assert inspection.start == 0x08000000
    assert inspection.end == 0x08000020
    assert ImageInspector().preview(inspection.image_id, 0x08000000, 16).data == bytes(range(16))


def test_hex_outside_flash_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.hex"
    image = IntelHex()
    image[0x09000000] = 0xAA
    image.write_hex_file(str(path))
    with pytest.raises(FlashError) as caught:
        ImageInspector().inspect(path, [FLASH])
    assert caught.value.code is FlashErrorCode.IMAGE_OUT_OF_RANGE
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_images.py -q
```

Expected: import failure for `ImageInspector`.

- [ ] **Step 3: Implement inspection**

Accept only `.hex` and `.bin`, verify content, calculate SHA-256, and store an in-memory metadata record keyed by a random URL-safe image ID. For HEX, convert `IntelHex.segments()` to immutable `ImageSegment` objects. For BIN, create one segment at `base_address` and raise `BIN_ADDRESS_MISSING` if absent.

Reject any segment not fully contained in one writable Flash region. Re-stat and re-hash immediately before job execution.

- [ ] **Step 4: Implement preview and sector coverage**

`preview(image_id, absolute_address, length)` returns at most 4096 bytes and marks gaps as absent rather than silently filling them with programmed bytes. `covered_sectors()` intersects segments with reliable pyOCD Flash regions; if sector geometry is unavailable, return an empty list plus `sector_operations_available=False`.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_images.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add mklink/cmsis_dap/images.py _maintainer/testing/tests/test_online_flash_images.py
git commit -m "feat: inspect HEX and BIN images"
```

## Task 7: Implement the pyOCD backend behind a fakeable protocol

**Files:**
- Create: `mklink/cmsis_dap/backend.py`
- Create: `_maintainer/testing/tests/test_online_flash_backend.py`

- [ ] **Step 1: Write a backend test with fake pyOCD session objects**

```python
from mklink.cmsis_dap.backend import PyOcdBackend


class FakeTarget:
    def __init__(self):
        self.calls = []

    def reset_and_halt(self):
        self.calls.append("reset_and_halt")

    def reset(self, reset_type=None):
        self.calls.append(("reset", reset_type))


class FakeSession:
    def __init__(self):
        self.target = FakeTarget()
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True


def test_connect_resets_and_halts_and_disconnects():
    session = FakeSession()
    backend = PyOcdBackend(session_factory=lambda probe, options: session)
    backend.connect(probe=object(), target="stm32f103c8", frequency=4_000_000, pack=None)
    backend.disconnect()
    assert session.target.calls == ["reset_and_halt"]
    assert session.closed is True
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_backend.py -q
```

Expected: import failure for `PyOcdBackend`.

- [ ] **Step 3: Implement session lifecycle**

Use lazy pyOCD imports. Resolve the selected probe by exact unique ID. Construct session options with `target_override`, `frequency`, `connect_mode`, `auto_unlock=False`, and the exact installed Pack path when required. Close an existing session before opening a new one.

- [ ] **Step 4: Implement operations and error mapping**

- `erase_chip()` uses `FlashEraser.Mode.CHIP`.
- `erase_sectors(addresses)` validates sector geometry before invoking sector erase.
- `program()` uses `FileProgrammer`, passing `base_address` only for BIN.
- `verify()` reads Flash in 4096-byte chunks and reports the first mismatch address.
- `reset_run()` maps configured reset modes.
- Every pyOCD exception maps to a stable `FlashErrorCode`; read-protection keywords map to `TARGET_LOCKED`.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_backend.py -q
```

Expected: all fake-session tests pass without connected hardware.

- [ ] **Step 6: Commit**

```powershell
git add mklink/cmsis_dap/backend.py _maintainer/testing/tests/test_online_flash_backend.py
git commit -m "feat: add pyOCD online flash backend"
```

## Task 8: Add the one-active-job manager and cancellation semantics

**Files:**
- Create: `mklink/cmsis_dap/jobs.py`
- Create: `_maintainer/testing/tests/test_online_flash_jobs.py`

- [ ] **Step 1: Write a failing closed-loop job test**

```python
from types import SimpleNamespace

from mklink.cmsis_dap.jobs import OnlineFlashJobManager
from mklink.cmsis_dap.models import JobRequest, JobState
from mklink.remote.resource_manager import ResourceManager


class FakeBackend:
    def __init__(self):
        self.calls = []

    def connect(self, **kwargs): self.calls.append("connect")
    def erase_chip(self): self.calls.append("erase")
    def program(self, **kwargs): self.calls.append("program")
    def verify(self, **kwargs): self.calls.append("verify")
    def reset_run(self): self.calls.append("reset")
    def disconnect(self): self.calls.append("disconnect")


def test_full_job_releases_resource():
    backend = FakeBackend()
    resource_manager = ResourceManager()
    manager = OnlineFlashJobManager(lambda: backend, resource_manager)
    inspected_image = SimpleNamespace(image_id="image-1", sha256="abc", file_path="app.bin")
    job_id = manager.start(JobRequest.full_sequence(inspected_image))
    snapshot = manager.wait(job_id, timeout=2)
    assert snapshot.state is JobState.SUCCEEDED
    assert backend.calls == ["connect", "erase", "program", "verify", "reset", "disconnect"]
    assert "target_debug" not in resource_manager.get_status()
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_jobs.py -q
```

Expected: import failure for `OnlineFlashJobManager`.

- [ ] **Step 3: Implement job execution and event retention**

Use a single `ThreadPoolExecutor(max_workers=1)`. Reject a second active job with `PROBE_BUSY`. Keep the active job and the last 20 completed snapshots. Store at most 5000 ordered events per job.

Every run uses:

```python
owner = f"user:online-flash:{job_id}"
resource_manager.acquire(ResourceGroup.TARGET_DEBUG, owner, preempt=request.preempt_ai)
try:
    self._execute_stages(job, backend)
finally:
    backend.disconnect()
    resource_manager.release(owner)
```

- [ ] **Step 4: Implement cancellation tests and code**

Add a fake backend whose `program()` waits on an event. Assert that `stop()` changes state to `STOPPING`, does not call `verify()` or `reset_run()`, disconnects after `program()` returns, and finishes `STOPPED`.

- [ ] **Step 5: Run tests**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_jobs.py -q
```

Expected: success, failure-cleanup, double-start, and stop-between-stages tests all pass.

- [ ] **Step 6: Commit**

```powershell
git add mklink/cmsis_dap/jobs.py _maintainer/testing/tests/test_online_flash_jobs.py
git commit -m "feat: add cancellable online flash jobs"
```

## Task 9: Expose the online-flash REST and SSE router

**Files:**
- Create: `mklink/remote/online_flash_api.py`
- Modify: `mklink/remote/api.py`
- Create: `_maintainer/testing/tests/test_online_flash_api.py`

- [ ] **Step 1: Write FastAPI contract tests**

```python
def test_target_search_returns_pack_state(client):
    response = client.get("/api/online-flash/targets", params={"q": "GD32F303"})
    assert response.status_code == 200
    assert response.json()[0]["part_number"] == "GD32F303RC"
    assert response.json()[0]["installed"] is False


def test_second_job_returns_conflict(client, active_job):
    response = client.post("/api/online-flash/jobs", json=active_job.request_json)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROBE_BUSY"
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_api.py -q
```

Expected: endpoints return 404.

- [ ] **Step 3: Implement router factory**

Define `create_online_flash_router(services: OnlineFlashServices) -> APIRouter`. Do not import global `_state` from `api.py`. `OnlineFlashServices` carries catalog, pack manager, image inspector, job manager, and probe provider.

Implement all endpoints from design section 13. Use HTTP 409 for active resource/job conflicts, 422 for image/target validation, 503 for first-use index failure, and 500 only for unmapped failures.

`POST /images/inspect` accepts `multipart/form-data` with `UploadFile`, `part_number`, and optional `base_address`. Stream the upload into the online-flash user cache while calculating SHA-256, enforce a configurable 256 MiB default limit, delete rejected uploads, and return only an opaque image ID to the browser. The job manager rechecks the cached file hash immediately before programming.

- [ ] **Step 4: Implement SSE replay**

`GET /jobs/{job_id}/events?after={sequence}` emits events newer than `after`, sends a heartbeat every 15 seconds, and closes after a terminal event. Reconnecting clients must not duplicate already acknowledged sequence numbers.

- [ ] **Step 5: Mount the router**

Create services once inside `create_fastapi_app()` and attach them to `app.state.online_flash`. Include the router under `/api/online-flash`. App shutdown stops the job executor and active Pack worker.

- [ ] **Step 6: Run API and full Python tests**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_api.py -q
python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 7: Commit**

```powershell
git add mklink/remote/online_flash_api.py mklink/remote/api.py _maintainer/testing/tests/test_online_flash_api.py
git commit -m "feat: expose online flash API"
```

## Task 10: Add route, API client, and top-level navigation

**Files:**
- Create: `gui/src/types/onlineFlash.ts`
- Create: `gui/src/composables/useOnlineFlashApi.ts`
- Create: `gui/src/views/OnlineFlashView.vue`
- Create: `gui/src/views/OnlineFlashView.test.ts`
- Modify: `gui/src/router.ts`
- Modify: `gui/src/App.vue`
- Modify: `gui/src/views/DashboardView.vue`

- [ ] **Step 1: Write navigation tests**

```typescript
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('online flash navigation', () => {
  it('registers a top-level online flash route', () => {
    const source = readFileSync('src/router.ts', 'utf8')
    expect(source).toContain("path: '/online-flash'")
    expect(source).toContain("name: 'online-flash'")
  })

  it('renames the legacy flash tab to offline flash', () => {
    const source = readFileSync('src/views/DashboardView.vue', 'utf8')
    expect(source).toContain('脱机烧录')
  })
})
```

- [ ] **Step 2: Verify failure**

```powershell
Set-Location gui
npm test -- src/views/OnlineFlashView.test.ts
```

Expected: tests fail because the route and label do not exist.

- [ ] **Step 3: Define TypeScript contracts and API client**

Types mirror Python JSON fields exactly: `ProbeRecord`, `TargetRecord`, `PackStatus`, `ImageInspection`, `PreviewPage`, `SectorRecord`, `JobRequest`, `JobSnapshot`, and `JobEvent`.

`useOnlineFlashApi()` exposes search, index update, install/import/remove Pack, inspect image, preview page, create/stop/get job, and `subscribeJob(jobId, afterSequence, onEvent)`. Firmware inspection uses `FormData` with an `UploadFile`, target part number, and optional BIN base address; do not force the shared JSON `Content-Type` header on this request.

- [ ] **Step 4: Register route and shell**

Add the navigation tab after Dashboard. `OnlineFlashView.vue` initially renders stable region landmarks:

```vue
<template>
  <div class="online-flash-grid">
    <aside data-zone="settings"></aside>
    <main data-zone="firmware"></main>
    <aside data-zone="flash-map"></aside>
    <section data-zone="logs"></section>
  </div>
</template>
```

- [ ] **Step 5: Run tests and build**

```powershell
npm test -- src/views/OnlineFlashView.test.ts
npm run build
```

Expected: tests pass and Vue TypeScript build exits 0.

- [ ] **Step 6: Commit**

```powershell
Set-Location ..
git add gui/src/router.ts gui/src/App.vue gui/src/views/DashboardView.vue gui/src/views/OnlineFlashView.vue gui/src/views/OnlineFlashView.test.ts gui/src/types/onlineFlash.ts gui/src/composables/useOnlineFlashApi.ts
git commit -m "feat: add online flash workspace"
```

## Task 11: Build the four-zone workspace and virtual preview

**Files:**
- Create: all files under `gui/src/components/online-flash/`
- Create: `gui/src/lib/hexPreview.ts`
- Create: `gui/src/lib/hexPreview.test.ts`
- Modify: `gui/src/views/OnlineFlashView.vue`
- Modify: `gui/src/views/OnlineFlashView.test.ts`

- [ ] **Step 1: Write preview formatting tests**

```typescript
import { describe, expect, it } from 'vitest'
import { formatHexRow } from './hexPreview'

describe('formatHexRow', () => {
  it('formats address, sixteen bytes, and ASCII', () => {
    const row = formatHexRow(0x08000000, Uint8Array.from([0x41, 0x00, 0x7e]))
    expect(row.address).toBe('08000000')
    expect(row.hex.slice(0, 3)).toEqual(['41', '00', '7E'])
    expect(row.ascii.slice(0, 3)).toBe('A.~')
  })
})
```

- [ ] **Step 2: Verify failure**

```powershell
npm test -- src/lib/hexPreview.test.ts
```

Expected: import failure for `formatHexRow`.

- [ ] **Step 3: Implement virtual preview**

Render only visible rows plus 20-row overscan. Fetch 4096-byte pages, cache at most 16 pages with LRU eviction, and abort stale fetches when the file or base address changes. HEX gaps render `--` and a blank ASCII cell.

- [ ] **Step 4: Implement panels and state rules**

- `ProbeSettingsPanel`: refresh, exact probe selection, SWD frequency, connect/reset modes.
- `TargetPackPanel`: debounced search, install confirmation, Pack progress/cancel, status badges.
- `FirmwareWorkspace`: file picker, HEX/BIN metadata, BIN base, virtual preview.
- `FlashMapPanel`: memory summary and sector selection only when geometry is reliable.
- `FlashActionBar`: actions, phase progress, total progress, stop-wait text.
- `FlashLogPanel`: bounded 5000-line virtual list, copy/export/clear.

Disable actions until probe, installed target, and valid image are selected. Confirm chip erase and selected-sector erase. Preserve selected target and SWD settings in local storage; never persist firmware file content.

- [ ] **Step 5: Extend view tests**

Mount with mocked API calls and assert BIN base validation, Pack download transition, button disabling, SSE replay sequence, and stop-wait state.

- [ ] **Step 6: Run frontend tests and build**

```powershell
npm test -- src/views/OnlineFlashView.test.ts src/lib/hexPreview.test.ts
npm run build
```

Expected: zero test failures and build exit 0.

- [ ] **Step 7: Commit**

```powershell
Set-Location ..
git add gui/src/components/online-flash gui/src/lib/hexPreview.ts gui/src/lib/hexPreview.test.ts gui/src/views/OnlineFlashView.vue gui/src/views/OnlineFlashView.test.ts
git commit -m "feat: complete online flash interface"
```

## Task 12: Package, integrate, and record hardware evidence

**Files:**
- Modify: `gui/src-tauri/tauri.conf.json` only if sidecar resource collection changes.
- Modify: `gui/src-tauri/src/lib.rs` only if user-data path/environment forwarding changes.
- Create: `docs/verification/online-flash-hil.md`
- Modify: `README.md`
- Modify: `references/commands-remote-gui.md`

- [ ] **Step 1: Run all automated online-flash tests**

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_dependencies.py `
  _maintainer/testing/tests/test_online_flash_errors.py `
  _maintainer/testing/tests/test_pack_catalog.py `
  _maintainer/testing/tests/test_pack_manager.py `
  _maintainer/testing/tests/test_online_flash_probes.py `
  _maintainer/testing/tests/test_online_flash_images.py `
  _maintainer/testing/tests/test_online_flash_backend.py `
  _maintainer/testing/tests/test_online_flash_jobs.py `
  _maintainer/testing/tests/test_online_flash_api.py -q
Set-Location gui
npm test -- src/views/OnlineFlashView.test.ts src/lib/hexPreview.test.ts
npm run build
Set-Location ..
```

Expected: zero failures.

- [ ] **Step 2: Verify repository and package size policy**

```powershell
git ls-files '*.pack'
Get-ChildItem -Recurse -Filter '*.pack' gui\src-tauri\target\release -ErrorAction SilentlyContinue
```

Expected: both commands return no bundled third-party Pack files.

- [ ] **Step 3: Run MKLink hardware matrix**

Record exact results for:

1. MKLink-only probe filtering with a second non-MKLink CMSIS-DAP connected if available.
2. Search a non-installed MCU and download one DFP.
3. Disconnect network and reuse the cached DFP.
4. Program and verify one HEX image.
5. Program and verify one BIN image with explicit base.
6. Exercise target disconnect, probe unplug, target power loss, stop during program, and verify mismatch.
7. Start RTT, attempt online flash, confirm conflict and controlled handoff.

- [ ] **Step 4: Write the evidence file**

Use this table header in `docs/verification/online-flash-hil.md`:

```markdown
| Date | MKLink | MCU | Pack ID/version | Image format/SHA-256 | Operation | Result | Duration | Notes |
|---|---|---|---|---|---|---|---|---|
```

Include commands and logs with serial numbers redacted.

- [ ] **Step 5: Build Tauri release**

```powershell
Set-Location gui
npx tauri build
```

Expected: release bundle generation exits 0 and a clean machine can update the index and install a Pack into user storage.

- [ ] **Step 6: Update user documentation**

Document online vs offline flash, Pack download/cache/remove, proxy behavior, BIN base address, resource conflicts, and the fact that “Pack 可用” is not “MKLink 已验证”.

- [ ] **Step 7: Run the complete regression suite**

```powershell
Set-Location ..
python -m pytest -q
Set-Location gui
npm test
npm run build
Set-Location ..
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 8: Commit and push checkpoint**

```powershell
git add README.md references/commands-remote-gui.md docs/verification/online-flash-hil.md gui/src-tauri
git commit -m "docs: qualify MKLink online flash"
git status --short
git push -u origin HEAD
```

Expected: the worktree is clean before push, and GitHub contains no `.pack` file.
