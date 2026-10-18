import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import HTTPException, UploadFile

from mklink.remote.api import create_app
from mklink.remote.dashboards import SuperWatchStreamManager
from route_utils import find_route
from test_peripheral_watch import SVD


def make_pack(path, model="IMPORTED_CHIP", pack_name="Import_DFP"):
    descriptor = f'''<package schemaVersion="1.7.0"><vendor>Test</vendor><name>{pack_name}</name>
    <description>Import test</description><url>https://example.com/</url>
    <releases><release version="1.0.0">test</release></releases><devices>
    <family Dfamily="Test" Dvendor="Test:1"><processor Dcore="Cortex-M3" Dclock="1000000"/>
    <device Dname="{model}"><memory name="IRAM1" start="0x20000000" size="0x1000" access="rwx"/>
    <debug svd="SVD/test.svd"/></device></family></devices></package>'''
    with ZipFile(path, "w") as archive:
        archive.writestr(f"Test.{pack_name}.pdsc", descriptor)
        archive.writestr("SVD/test.svd", SVD)


def test_pack_import_and_removal_invalidate_warm_svd_index(tmp_path, monkeypatch):
    from mklink.cmsis_dap.pack_manager import PackManager
    import mklink.peripheral_watch as peripherals
    cache = tmp_path / "packs"
    monkeypatch.setenv("MKLINK_PYOCD_HOME", str(cache))
    monkeypatch.setattr("mklink.cmsis_dap.builtin_pack_bundle.load_builtin_pack_records", lambda: [])
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty")
    monkeypatch.delenv("ARM_PACK_ROOT", raising=False)
    monkeypatch.delenv("CMSIS_PACK_ROOT", raising=False)
    discover = peripherals.discover_svd_targets
    calls = []
    def tracked(root):
        calls.append(root)
        return discover(root)
    monkeypatch.setattr(peripherals, "discover_svd_targets", tracked)
    app = create_app(project_root=str(tmp_path))
    targets = find_route(app, "/api/dash/superwatch/peripherals/targets").endpoint
    source = tmp_path / "test.pack"
    make_pack(source)
    manager = PackManager(cache)
    baseline = tmp_path / "baseline.pack"
    make_pack(baseline, "BASE_CHIP", "Base_DFP")
    manager.import_pack(baseline, lambda event: None)

    async def verify():
        assert not (await targets(q="IMPORTED_CHIP"))["targets"]
        assert (await targets(q="BASE_CHIP"))["targets"]
        assert len(calls) == 1  # A nonempty cached index must be invalidated.
        manager.import_pack(source, lambda event: None)
        result = (await targets(q="IMPORTED_CHIP"))["targets"]
        assert len(result) == 1 and result[0]["svd"] == "SVD/test.svd"
        await targets(q="IMPORTED_CHIP")
        assert len(calls) == 2
        await targets(q="IMPORTED_CHIP", refresh=True)
        assert len(calls) == 3
        manager.remove("Test", "Import_DFP", "1.0.0")
        assert not (await targets(q="IMPORTED_CHIP"))["targets"]
        assert len(calls) == 4
    asyncio.run(verify())


def setup_app(tmp_path, monkeypatch):
    manager = SuperWatchStreamManager()
    managers = {name: SimpleNamespace() for name in ("systemview", "rtt", "vofa", "serial", "modbus")}
    managers["superwatch"] = manager
    monkeypatch.setattr("mklink.remote.dashboards.get_managers", lambda: managers)
    device = SimpleNamespace(connected=True, _project_root=str(tmp_path), symbol_catalog=None)
    manager.prepare(device)
    app = create_app(project_root=str(tmp_path))
    app.state.mklink_state["device"] = device
    return app, manager, device


def test_svd_upload_select_restore_and_active_capture_rejection(tmp_path, monkeypatch):
    app, manager, device = setup_app(tmp_path, monkeypatch)
    upload = find_route(app, "/api/files/svd").endpoint
    select = find_route(app, "/api/dash/superwatch/peripherals/select").endpoint
    async def verify():
        saved = await upload(UploadFile(filename="device.SVD", file=io.BytesIO(SVD)))
        path = Path(saved["path"])
        assert path.parent == tmp_path / ".mklink/uploads/file-sources"
        assert path.read_bytes() == SVD
        again = await upload(UploadFile(filename="another.svd", file=io.BytesIO(SVD)))
        assert again["path"] == saved["path"]
        result = await select(target_id=None, chip=None, svd=str(path))
        assert result["selection"]["pack"] == "local"
        assert any(i["name"] == "GPIOB.12" for i in result["items"])
        manager.add_watch("GPIOB.12")
        manager._running = True
        manager._stop_event.clear()
        with pytest.raises(HTTPException) as error:
            await select(target_id=None, chip=None, svd=str(path))
        assert error.value.status_code == 409
        assert [i.name for i in manager._runtime.items] == ["GPIOB.12"]
        manager._running = False
        restored = SuperWatchStreamManager()
        restored.prepare(device)
        assert restored.peripheral_catalog()["selection"] == result["selection"]
        assert restored.peripheral_catalog()["items"] == result["items"]
    asyncio.run(verify())


@pytest.mark.parametrize("name,data", [("bad.xml", SVD), ("empty.svd", b""),
    ("bad.svd", b"<device>"), ("wrong.svd", SVD.replace(b"device", b"package")),
    ("no_registers.svd", b"<device><name>Empty</name></device>")])
def test_invalid_svd_is_not_published_or_selected(tmp_path, monkeypatch, name, data):
    app, manager, _ = setup_app(tmp_path, monkeypatch)
    upload = find_route(app, "/api/files/svd").endpoint
    before = manager.peripheral_catalog()
    async def verify():
        with pytest.raises(HTTPException) as error:
            await upload(UploadFile(filename=name, file=io.BytesIO(data)))
        assert error.value.status_code == 400
    asyncio.run(verify())
    assert manager.peripheral_catalog() == before
    assert not list((tmp_path / ".mklink/uploads/file-sources").glob("*"))


def test_svd_upload_limit_is_enforced_before_publish(tmp_path, monkeypatch):
    monkeypatch.setattr("mklink.peripheral_watch.MAX_XML_BYTES", 16)
    app, _, _ = setup_app(tmp_path, monkeypatch)
    async def verify():
        with pytest.raises(HTTPException) as error:
            await find_route(app, "/api/files/svd").endpoint(UploadFile(filename="large.svd", file=io.BytesIO(SVD)))
        assert error.value.status_code == 400
    asyncio.run(verify())
    assert not list((tmp_path / ".mklink/uploads/file-sources").glob("*"))
