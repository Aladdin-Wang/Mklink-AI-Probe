import importlib.util
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest


AUDIT_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "tauri-gui-builder"
    / "scripts"
    / "pack_license_audit.py"
)


@pytest.fixture
def audit_module():
    spec = importlib.util.spec_from_file_location("mklink_pack_license_audit", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_pack(
    path: Path,
    *,
    license_value: str | None,
    include_license: bool,
) -> Path:
    license_xml = "<license>{}</license>".format(license_value) if license_value else ""
    descriptor = (
        "<package><vendor>Vendor</vendor><name>Device_DFP</name>"
        "<url>https://vendor.example/packs/</url>"
        f"{license_xml}"
        '<releases><release version="1.0.0"/></releases>'
        '<devices><family Dvendor="Vendor:1" Dfamily="Device"><device Dname="DEVICE_A">'
        '<algorithm name="Flash/Device.FLM" start="0x08000000" size="0x1000"/>'
        "</device></family></devices></package>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("Vendor.Device_DFP.pdsc", descriptor)
        archive.writestr("Flash/Device.FLM", b"algorithm")
        archive.writestr("Examples/large.bin", b"not selected")
        if include_license:
            archive.writestr("LICENSE.txt", b"Apache-2.0")
    return path


def test_audit_pack_reports_complete_license_and_slim_inventory(audit_module, tmp_path):
    pack = write_pack(
        tmp_path / "Vendor.Device_DFP.1.0.0.pack",
        license_value="LICENSE.txt",
        include_license=True,
    )

    result = audit_module.audit_pack(pack)

    assert result.classification == "declared-present"
    assert result.pack_id == "Vendor.Device_DFP"
    assert result.version == "1.0.0"
    assert result.source_url == "https://vendor.example/packs/"
    assert result.license_files == ("LICENSE.txt",)
    assert result.missing_license_files == ()
    assert result.referenced_algorithms == ("Flash/Device.FLM",)
    assert result.target_count == 1
    assert result.slim_file_count == 3
    assert result.slim_uncompressed_bytes == len(b"algorithm") + len(b"Apache-2.0") + len(
        ZipFile(pack).read("Vendor.Device_DFP.pdsc")
    )
    assert len(result.sha256) == 64


def test_audit_pack_distinguishes_removed_and_absent_license_evidence(
    audit_module, tmp_path
):
    missing = write_pack(
        tmp_path / "Vendor.Missing_DFP.1.0.0.pack",
        license_value="LICENSE.txt",
        include_license=False,
    )
    absent = write_pack(
        tmp_path / "Vendor.Absent_DFP.1.0.0.pack",
        license_value=None,
        include_license=False,
    )

    missing_result = audit_module.audit_pack(missing)
    absent_result = audit_module.audit_pack(absent)

    assert missing_result.classification == "declared-missing"
    assert missing_result.license_files == ()
    assert missing_result.missing_license_files == ("LICENSE.txt",)
    assert absent_result.classification == "no-license-evidence"
    assert absent_result.license_files == ()
    assert absent_result.missing_license_files == ()


def test_audit_root_sorts_results_and_counts_classifications(audit_module, tmp_path):
    write_pack(
        tmp_path / "z.pack", license_value="LICENSE.txt", include_license=False
    )
    write_pack(
        tmp_path / "a.pack", license_value="LICENSE.txt", include_license=True
    )

    report = audit_module.audit_root(tmp_path)

    assert [record.file_name for record in report.records] == ["a.pack", "z.pack"]
    assert report.counts == {"declared-missing": 1, "declared-present": 1}


def test_audit_pack_rejects_descriptor_path_escape(audit_module, tmp_path):
    pack = write_pack(
        tmp_path / "unsafe.pack",
        license_value="../LICENSE.txt",
        include_license=False,
    )

    with pytest.raises(ValueError, match="safe relative path"):
        audit_module.audit_pack(pack)
