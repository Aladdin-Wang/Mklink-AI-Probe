import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from mklink.cmsis_dap.algorithm_catalog import (
    deploy_algorithm_to_probe,
    discover_flash_algorithms,
    extract_algorithm,
    resolve_firmware_algorithms,
)
from mklink.cmsis_dap.models import TargetRecord
from mklink.cmsis_dap.paths import PackPaths


def _pack(path: Path, version: str, internal: bytes, external: bytes) -> Path:
    descriptor = f"""<?xml version="1.0" encoding="UTF-8"?>
<package schemaVersion="1.7.0">
  <vendor>Vendor</vendor><name>Device_DFP</name>
  <releases><release version="{version}">Test</release></releases>
  <devices><family Dfamily="Test" Dvendor="Vendor:1">
    <processor Dcore="Cortex-M7" Dfpu="DP_FPU" Dmpu="MPU" Dendian="Little-endian"/>
    <device Dname="DEVICE_A">
      <memory name="IROM1" start="0x08000000" size="0x20000" access="rx" default="1" startup="1"/>
      <memory name="IRAM1" start="0x20000000" size="0x20000" access="rwx" default="1"/>
      <algorithm name="Flash/Internal.FLM" start="0x08000000" size="0x20000" RAMstart="0x20001000" default="1"/>
      <algorithm name="Flash/External.FLM" start="0x90000000" size="0x800000" RAMstart="0x20002000"/>
    </device>
  </family></devices>
</package>"""
    with ZipFile(path, "w") as archive:
        archive.writestr("Vendor.Device_DFP.pdsc", descriptor)
        archive.writestr("Flash/Internal.FLM", internal)
        archive.writestr("Flash/External.FLM", external)
    return path


def _record(pack: Path, version: str, source: str) -> TargetRecord:
    return TargetRecord(
        part_number="DEVICE_A",
        vendor="Vendor",
        pack_id="Vendor.Device_DFP",
        pack_version=version,
        pack_path=str(pack),
        installed=True,
        source=source,
    )


def test_user_pack_precedes_bundle_and_exposes_all_exact_device_regions(tmp_path: Path):
    paths = PackPaths(tmp_path / "cache")
    paths.data_dir.mkdir(parents=True)
    installed = _pack(paths.data_dir / "installed.pack", "2.0.0", b"new-internal", b"new-external")
    bundled = _pack(tmp_path / "bundled.pack", "1.0.0", b"old-internal", b"old-external")
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.state_file.write_text(json.dumps({
        "installed": {"Vendor.Device_DFP": {"2.0.0": str(installed)}},
    }), encoding="utf-8")

    algorithms = discover_flash_algorithms(
        "DEVICE_A",
        paths=paths,
        builtin_provider=lambda: [_record(bundled, "1.0.0", "bundle")],
    )

    assert [algorithm.file_name for algorithm in algorithms] == ["Internal.FLM", "External.FLM"]
    assert {algorithm.source_kind for algorithm in algorithms} == {"installed-pack"}
    assert {algorithm.source_name for algorithm in algorithms} == {"Vendor.Device_DFP@2.0.0"}
    assert extract_algorithm(algorithms[1]) == b"new-external"


def test_state_pack_outside_managed_data_directory_is_ignored(tmp_path: Path):
    paths = PackPaths(tmp_path / "cache")
    paths.root.mkdir(parents=True)
    outside = _pack(tmp_path / "outside.pack", "2.0.0", b"outside", b"outside-ext")
    bundled = _pack(tmp_path / "bundled.pack", "1.0.0", b"builtin", b"builtin-ext")
    paths.state_file.write_text(json.dumps({
        "installed": {"Vendor.Device_DFP": {"2.0.0": str(outside)}},
    }), encoding="utf-8")

    algorithms = discover_flash_algorithms(
        "DEVICE_A",
        paths=paths,
        builtin_provider=lambda: [_record(bundled, "1.0.0", "bundle")],
    )

    assert extract_algorithm(algorithms[0]) == b"builtin"
    assert {algorithm.source_kind for algorithm in algorithms} == {"builtin-pack"}


def test_bundle_is_used_offline_and_firmware_ranges_select_external_flash(tmp_path: Path):
    paths = PackPaths(tmp_path / "cache")
    bundled = _pack(tmp_path / "bundled.pack", "1.0.0", b"internal", b"external")
    algorithms = discover_flash_algorithms(
        "DEVICE_A",
        paths=paths,
        builtin_provider=lambda: [_record(bundled, "1.0.0", "bundle")],
    )

    selected = resolve_firmware_algorithms(
        algorithms,
        ((0x90001000, 0x90002000),),
    )

    assert len(selected) == 1
    assert selected[0].algorithm.file_name == "External.FLM"
    assert selected[0].ranges == ((0x90001000, 0x90002000),)


def test_extract_algorithm_writes_content_addressed_verified_payload(tmp_path: Path):
    pack = _pack(tmp_path / "bundle.pack", "1.0.0", b"internal", b"external")
    algorithm = discover_flash_algorithms(
        "DEVICE_A",
        paths=PackPaths(tmp_path / "cache"),
        builtin_provider=lambda: [_record(pack, "1.0.0", "bundle")],
    )[0]

    destination = extract_algorithm(algorithm, tmp_path / "out")

    assert destination.is_file()
    assert destination.suffix.casefold() == ".flm"
    assert hashlib.sha256(destination.read_bytes()).hexdigest() in destination.name
    assert extract_algorithm(algorithm, tmp_path / "out") == destination

    probe_path = deploy_algorithm_to_probe(algorithm, disk_root=tmp_path / "probe")
    deployed = (tmp_path / "probe").joinpath(*probe_path.strip("/").split("/"))
    assert deployed.read_bytes() == b"internal"
    assert hashlib.sha256(b"internal").hexdigest() in deployed.name


def test_hpm_targets_never_resolve_flm_algorithms(tmp_path: Path):
    def unexpected_builtin_provider():
        raise AssertionError("HPM targets must not inspect Pack algorithms")

    assert discover_flash_algorithms(
        "HPM5301xEGx",
        paths=PackPaths(tmp_path / "cache"),
        builtin_provider=unexpected_builtin_provider,
    ) == []
