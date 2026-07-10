import builtins
import json
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pytest

from mklink.cmsis_dap.models import TargetRecord
from mklink.cmsis_dap.pack_catalog import PackCatalog
from mklink.cmsis_dap.paths import PackPaths


def _write_index(paths, targets):
    paths.index_dir.mkdir(parents=True, exist_ok=True)
    paths.index_file.write_text(json.dumps(targets), encoding="utf-8")


def _index_target(vendor, pack, version):
    return {
        "name": "target",
        "from_pack": {
            "vendor": vendor,
            "pack": pack,
            "version": version,
        },
        "algorithms": [],
        "memories": {},
    }


def _write_state(paths, installed):
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.state_file.write_text(
        json.dumps({"installed": installed}),
        encoding="utf-8",
    )


def test_searches_cached_index_case_insensitively(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {
            "GD32F303RC": _index_target(
                "GigaDevice",
                "GD32F30x_DFP",
                "3.0.2",
            )
        },
    )

    results = PackCatalog(paths, builtin_provider=lambda: []).search("gd32f303")

    assert len(results) == 1
    assert results[0].part_number == "GD32F303RC"
    assert results[0].installed is False
    assert results[0].pack_id == "GigaDevice.GD32F30x_DFP"
    assert results[0].pack_version == "3.0.2"
    assert results[0].source == "index"


def test_installed_registry_marks_exact_pack_version_and_path(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {
            "GD32F303RC": _index_target(
                "GigaDevice",
                "GD32F30x_DFP",
                "3.0.2",
            )
        },
    )
    pack_path = tmp_path / "cache" / "GigaDevice.GD32F30x_DFP.3.0.2.pack"
    pack_path.parent.mkdir()
    pack_path.write_bytes(b"pack")
    _write_state(
        paths,
        {
            "GigaDevice.GD32F30x_DFP": {
                "3.0.2": str(pack_path),
            }
        },
    )

    result = PackCatalog(paths, builtin_provider=lambda: []).search("GD32F303RC")[0]

    assert result.installed is True
    assert result.pack_path == str(pack_path)


@pytest.mark.parametrize(
    "installed",
    [
        {
            "GigaDevice.GD32F30x_DFP": {
                "3.0.1": "unused.pack",
            }
        },
        {
            "GigaDevice.Other_DFP": {
                "3.0.2": "unused.pack",
            }
        },
    ],
)
def test_installed_registry_requires_exact_pack_id_and_version(tmp_path, installed):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {
            "GD32F303RC": _index_target(
                "GigaDevice",
                "GD32F30x_DFP",
                "3.0.2",
            )
        },
    )
    _write_state(paths, installed)

    result = PackCatalog(paths, builtin_provider=lambda: []).search("GD32F303RC")[0]

    assert result.installed is False
    assert result.pack_path is None


def test_installed_registry_ignores_stale_pack_path(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {
            "GD32F303RC": _index_target(
                "GigaDevice",
                "GD32F30x_DFP",
                "3.0.2",
            )
        },
    )
    missing_pack = tmp_path / "missing.pack"
    _write_state(
        paths,
        {
            "GigaDevice.GD32F30x_DFP": {
                "3.0.2": str(missing_pack),
            }
        },
    )

    result = PackCatalog(paths, builtin_provider=lambda: []).search("GD32F303RC")[0]

    assert result.installed is False
    assert result.pack_path is None


def test_corrupt_state_does_not_hide_valid_index(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    paths.state_file.write_text("{not-json", encoding="utf-8")
    catalog = PackCatalog(paths, builtin_provider=lambda: [])

    assert [record.part_number for record in catalog.search("")] == ["STM32F103C8"]
    status = catalog.status()
    assert status.index_available is True
    assert status.last_error is not None
    assert "state" in status.last_error


def test_refresh_failure_keeps_last_good_cached_index(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {
            "STM32F103C8": _index_target(
                "STMicroelectronics",
                "STM32F1xx_DFP",
                "2.4.1",
            )
        },
    )
    catalog = PackCatalog(paths, builtin_provider=lambda: [])

    catalog.note_refresh_failure("offline")
    results = catalog.search("stm32f103")

    assert [record.part_number for record in results] == ["STM32F103C8"]
    assert catalog.status().last_error == "offline"


def test_new_valid_index_clears_refresh_failure(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    catalog = PackCatalog(paths, builtin_provider=lambda: [])
    catalog.note_refresh_failure("offline")
    assert [record.part_number for record in catalog.search("")] == ["STM32F103C8"]
    assert catalog.status().last_error == "offline"
    failed_signature = (paths.index_file.stat().st_mtime_ns, paths.index_file.stat().st_size)

    _write_index(
        paths,
        {
            "GD32F303RC-LONGER": _index_target(
                "GigaDevice",
                "GD32F30x_DFP",
                "3.0.2",
            )
        },
    )
    refreshed_signature = (paths.index_file.stat().st_mtime_ns, paths.index_file.stat().st_size)
    assert refreshed_signature != failed_signature

    assert [record.part_number for record in catalog.search("")] == ["GD32F303RC-LONGER"]
    assert catalog.status().last_error is None


def test_pack_paths_use_explicit_root_without_creating_directories(tmp_path):
    root = tmp_path / "pyocd-home"

    paths = PackPaths(root=root)

    assert is_dataclass(paths)
    assert paths.__dataclass_params__.frozen
    assert paths.index_dir == root / "index"
    assert paths.index_file == root / "index" / "index.json"
    assert paths.aliases_file == root / "index" / "aliases.json"
    assert paths.data_dir == root / "data"
    assert paths.staging_dir == root / "staging"
    assert paths.state_file == root / "state.json"
    assert not root.exists()
    with pytest.raises(FrozenInstanceError):
        paths.root = tmp_path


def test_pack_paths_prefer_environment_override(monkeypatch, tmp_path):
    configured = tmp_path / "configured"
    monkeypatch.setenv("MKLINK_PYOCD_HOME", str(configured))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert PackPaths().root == configured


def test_pack_paths_use_local_app_data_default(monkeypatch, tmp_path):
    local_app_data = tmp_path / "local"
    monkeypatch.delenv("MKLINK_PYOCD_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    assert PackPaths().root == local_app_data / "MKLink" / "pyocd"


def test_pack_paths_have_explicit_fallback_without_local_app_data(monkeypatch):
    monkeypatch.delenv("MKLINK_PYOCD_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert PackPaths().root == Path.home() / "AppData" / "Local" / "MKLink" / "pyocd"


def test_search_filters_sorts_and_limits_merged_records(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {
            "STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1"),
            "gd32f303rc": _index_target("GigaDevice", "GD32F30x_DFP", "3.0.2"),
            "GD32F103C8": _index_target("GigaDevice", "GD32F10x_DFP", "1.2.0"),
        },
    )
    builtins = [
        TargetRecord(
            part_number="GD32F450ZI",
            vendor="GigaDevice",
            installed=True,
            source="builtin",
        )
    ]
    catalog = PackCatalog(paths, builtin_provider=lambda: builtins)

    results = catalog.search("32", vendor="gigadevice", installed=False, limit=2)

    assert [record.part_number for record in results] == ["GD32F103C8", "gd32f303rc"]
    assert catalog.search("", installed=True) == builtins
    assert catalog.search("", limit=0) == []
    assert catalog.search("", limit=-1) == []


def test_duplicate_part_number_prefers_installed_builtin_record(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    builtin = TargetRecord(
        part_number="stm32f103c8",
        vendor="STMicroelectronics",
        installed=True,
        source="builtin",
    )

    results = PackCatalog(paths, builtin_provider=lambda: [builtin]).search("STM32")

    assert results == [builtin]


def test_duplicate_uninstalled_part_number_prefers_builtin_record(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    builtin = TargetRecord(
        part_number="stm32f103c8",
        vendor="STMicroelectronics",
        installed=False,
        source="builtin",
    )

    results = PackCatalog(paths, builtin_provider=lambda: [builtin]).search("STM32")

    assert results == [builtin]


@pytest.mark.parametrize("index_contents", [None, "{not-json"])
def test_unavailable_index_falls_back_to_builtins_and_records_error(
    tmp_path,
    index_contents,
):
    paths = PackPaths(root=tmp_path)
    if index_contents is not None:
        paths.index_dir.mkdir(parents=True)
        paths.index_file.write_text(index_contents, encoding="utf-8")
    builtin = TargetRecord(
        part_number="cortex_m",
        vendor="Arm",
        installed=True,
        source="builtin",
    )
    catalog = PackCatalog(paths, builtin_provider=lambda: [builtin])

    assert catalog.search("cortex") == [builtin]
    status = catalog.status()
    assert status.last_error
    assert status.index_available is False
    assert status.target_count == 1
    if index_contents is not None:
        assert paths.index_file.read_text(encoding="utf-8") == index_contents


def test_valid_index_status_is_available_and_counts_merged_targets(tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    builtin = TargetRecord(
        part_number="cortex_m",
        vendor="Arm",
        installed=True,
        source="builtin",
    )
    catalog = PackCatalog(paths, builtin_provider=lambda: [builtin])

    assert catalog.status().index_available is False
    catalog.search("")
    status = catalog.status()

    assert is_dataclass(status)
    assert status.__dataclass_params__.frozen
    assert status.last_error is None
    assert status.index_available is True
    assert status.target_count == 2


def test_catalog_caches_builtins_and_index_until_index_signature_changes(
    monkeypatch,
    tmp_path,
):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    initial_signature = (paths.index_file.stat().st_mtime_ns, paths.index_file.stat().st_size)
    calls = {"builtin": 0, "index_open": 0}

    def builtin_provider():
        calls["builtin"] += 1
        return []

    original_open = Path.open

    def counting_open(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == paths.index_file and mode == "r":
            calls["index_open"] += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    catalog = PackCatalog(paths, builtin_provider=builtin_provider)
    assert [item.part_number for item in catalog.search("")] == ["STM32F103C8"]
    assert [item.part_number for item in catalog.search("")] == ["STM32F103C8"]
    assert calls == {"builtin": 1, "index_open": 1}

    _write_index(
        paths,
        {
            "GD32F303RC-LONGER": _index_target(
                "GigaDevice",
                "GD32F30x_DFP",
                "3.0.2",
            )
        },
    )
    changed_signature = (paths.index_file.stat().st_mtime_ns, paths.index_file.stat().st_size)
    assert changed_signature != initial_signature

    assert [item.part_number for item in catalog.search("")] == ["GD32F303RC-LONGER"]
    assert calls == {"builtin": 1, "index_open": 2}


def test_catalog_caches_state_until_state_signature_changes(monkeypatch, tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"GD32F303RC": _index_target("GigaDevice", "GD32F30x_DFP", "3.0.2")},
    )
    pack_path = tmp_path / "installed.pack"
    pack_path.write_bytes(b"pack")
    _write_state(
        paths,
        {"GigaDevice.GD32F30x_DFP": {"3.0.2": str(pack_path)}},
    )
    initial_signature = (paths.state_file.stat().st_mtime_ns, paths.state_file.stat().st_size)
    state_opens = 0
    original_open = Path.open

    def counting_open(path, *args, **kwargs):
        nonlocal state_opens
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == paths.state_file and mode == "r":
            state_opens += 1
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    catalog = PackCatalog(paths, builtin_provider=lambda: [])

    assert catalog.search("")[0].installed is True
    assert catalog.search("")[0].installed is True
    assert state_opens == 1

    _write_state(paths, {})
    changed_signature = (paths.state_file.stat().st_mtime_ns, paths.state_file.stat().st_size)
    assert changed_signature != initial_signature
    assert catalog.search("")[0].installed is False
    assert state_opens == 2


def test_catalog_retries_index_after_transient_read_failure(monkeypatch, tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    original_open = Path.open
    index_opens = 0

    def fail_first_index_read(path, *args, **kwargs):
        nonlocal index_opens
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == paths.index_file and mode == "r":
            index_opens += 1
            if index_opens == 1:
                raise PermissionError("sharing violation")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_first_index_read)
    catalog = PackCatalog(paths, builtin_provider=lambda: [])

    assert catalog.search("") == []
    assert catalog.status().last_error is not None
    assert [record.part_number for record in catalog.search("")] == ["STM32F103C8"]
    assert catalog.status().last_error is None
    assert catalog.status().index_available is True
    assert index_opens == 2


def test_catalog_retries_state_after_transient_read_failure(monkeypatch, tmp_path):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"GD32F303RC": _index_target("GigaDevice", "GD32F30x_DFP", "3.0.2")},
    )
    pack_path = tmp_path / "installed.pack"
    pack_path.write_bytes(b"pack")
    _write_state(
        paths,
        {"GigaDevice.GD32F30x_DFP": {"3.0.2": str(pack_path)}},
    )
    original_open = Path.open
    state_opens = 0

    def fail_first_state_read(path, *args, **kwargs):
        nonlocal state_opens
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == paths.state_file and mode == "r":
            state_opens += 1
            if state_opens == 1:
                raise PermissionError("sharing violation")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_first_state_read)
    catalog = PackCatalog(paths, builtin_provider=lambda: [])

    first = catalog.search("")[0]
    assert first.installed is False
    assert first.pack_path is None
    assert catalog.status().last_error is not None

    second = catalog.search("")[0]
    assert second.installed is True
    assert second.pack_path == str(pack_path)
    assert catalog.status().last_error is None
    assert state_opens == 2


@pytest.mark.parametrize("break_index", ["corrupt", "missing"])
def test_catalog_uses_in_memory_last_good_index_after_read_failure(
    tmp_path,
    break_index,
):
    paths = PackPaths(root=tmp_path)
    _write_index(
        paths,
        {"STM32F103C8": _index_target("ST", "STM32F1xx_DFP", "2.4.1")},
    )
    catalog = PackCatalog(paths, builtin_provider=lambda: [])
    assert [record.part_number for record in catalog.search("")] == ["STM32F103C8"]

    if break_index == "corrupt":
        paths.index_file.write_text("{not-json", encoding="utf-8")
    else:
        paths.index_file.unlink()

    assert [record.part_number for record in catalog.search("")] == ["STM32F103C8"]
    status = catalog.status()
    assert status.last_error is not None
    assert status.index_available is True
    assert status.target_count == 1


def test_injected_provider_does_not_import_pyocd(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "pyocd" or name.startswith("pyocd."):
            raise AssertionError("pyOCD must remain lazy with an injected provider")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    catalog = PackCatalog(PackPaths(root=tmp_path), builtin_provider=lambda: [])

    assert catalog.search("") == []
