import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import zlib

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "tauri-gui-builder"
    / "scripts"
    / "daplinkutility_resources.py"
)


@pytest.fixture
def resources_module():
    spec = importlib.util.spec_from_file_location(
        "mklink_daplinkutility_resources", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _qt_fixture():
    names = bytearray()
    offsets = {}
    for name in ("resources", "algorithms", "chips.json", "DEVICE.FLM"):
        offsets[name] = len(names)
        encoded = name.encode("utf-16-be")
        names.extend(struct.pack(">HI", len(name), 0))
        names.extend(encoded)

    data = bytearray()

    def add_payload(payload, compressed=False):
        offset = len(data)
        stored = struct.pack(">I", len(payload)) + zlib.compress(payload) \
            if compressed else payload
        data.extend(struct.pack(">I", len(stored)))
        data.extend(stored)
        return offset

    chips = json.dumps({"Vendor": {"Family": {}}}).encode()
    flm = b"ELF-FLM-PAYLOAD"
    chips_offset = add_payload(chips)
    flm_offset = add_payload(flm, compressed=True)

    def directory(name, count, child):
        return struct.pack(">IHI IQ", offsets.get(name, 0), 0x02, count, child, 0)

    def file(name, offset, compressed=False):
        return struct.pack(
            ">IHHHIQ", offsets[name], 0x01 if compressed else 0, 0, 0, offset, 0
        )

    tree = b"".join((
        directory("", 1, 1),
        directory("resources", 2, 2),
        directory("algorithms", 1, 4),
        file("chips.json", chips_offset),
        file("DEVICE.FLM", flm_offset, compressed=True),
    ))
    return bytes(tree), bytes(names), bytes(data), chips, flm


def test_qt_resource_reader_walks_tree_and_decompresses_payloads(resources_module):
    tree, names, data, chips, flm = _qt_fixture()

    resources = resources_module.QtResourceReader(tree, names, data).files()

    assert resources == {
        "resources/algorithms/DEVICE.FLM": flm,
        "resources/chips.json": chips,
    }


def test_qt_resource_reader_rejects_out_of_bounds_tree_entries(resources_module):
    tree, names, data, _chips, _flm = _qt_fixture()
    corrupted = bytearray(tree)
    corrupted[10:14] = struct.pack(">I", 0xFFFFFFFF)

    with pytest.raises(ValueError, match="tree"):
        resources_module.QtResourceReader(bytes(corrupted), names, data).files()


def test_runtime_locator_recovers_padded_qt_resource_arrays(resources_module):
    tree, names, data, chips, flm = _qt_fixture()
    region = b"ignored-prefix" + tree + b"\x00" * 11 + names + b"\x00" * 13 + data

    recovered = resources_module._runtime_arrays_from_regions([region])
    resources = resources_module.QtResourceReader(*recovered).files()

    assert resources == {
        "resources/algorithms/DEVICE.FLM": flm,
        "resources/chips.json": chips,
    }


def test_build_bundle_filters_references_and_deduplicates_by_sha256(
    resources_module, tmp_path
):
    shared = b"same-flm"
    extra = b"unused-flm"
    catalog = {
        "Vendor": {
            "Family": {
                "PART-A": {
                    "rambase": "0x20000000",
                    "ramsize": "0x1000",
                    "algooptb": "OPTION.FLM",
                    "algoprog": [{
                        "flashbase": "0x08000000",
                        "flashsize": "0x10000",
                        "algorithm": "MAIN.FLM",
                    }],
                },
                "PART-B": {
                    "rambase": "0x20000000",
                    "ramsize": "0x2000",
                    "algoprog": [{
                        "flashbase": "0x90000000",
                        "flashsize": "0x800000",
                        "algorithm": "ALIAS.FLM",
                    }],
                },
            }
        }
    }
    resources = {
        "resources/chips.json": json.dumps(catalog).encode(),
        "resources/algorithms/MAIN.FLM": shared,
        "resources/algorithms/ALIAS.FLM": shared,
        "resources/algorithms/OPTION.FLM": b"option",
        "resources/algorithms/UNUSED.FLM": extra,
    }

    manifest = resources_module.build_bundle_from_resources(
        resources,
        tmp_path / "bundle",
        source_sha256="a" * 64,
    )

    assert manifest["target_count"] == 2
    assert manifest["referenced_algorithm_count"] == 3
    assert manifest["blob_count"] == 2
    assert manifest["unreferenced_algorithm_count"] == 1
    assert len(list((tmp_path / "bundle" / "blobs").rglob("*.flm"))) == 2
    part_a = manifest["targets"][0]
    assert part_a["part_number"] == "PART-A"
    assert part_a["algorithms"][0]["sha256"] == hashlib.sha256(shared).hexdigest()
    assert part_a["option_algorithm"]["file_name"] == "OPTION.FLM"


def test_build_bundle_rejects_unsafe_or_missing_algorithm_names(resources_module, tmp_path):
    catalog = {
        "Vendor": {"Family": {"PART": {
            "rambase": "0x20000000",
            "ramsize": "0x1000",
            "algoprog": [{
                "flashbase": "0x08000000",
                "flashsize": "0x10000",
                "algorithm": "../SECRET.FLM",
            }],
        }}}
    }

    with pytest.raises(ValueError, match="safe resource name"):
        resources_module.build_bundle_from_resources(
            {"resources/chips.json": json.dumps(catalog).encode()},
            tmp_path / "bundle",
            source_sha256="b" * 64,
        )


def test_build_bundle_tolerates_missing_optional_algorithm(resources_module, tmp_path):
    catalog = {
        "Vendor": {"Family": {"PART": {
            "rambase": "0x20000000",
            "ramsize": "0x1000",
            "algooptb": "MISSING-OPTION.FLM",
            "algoprog": [{
                "flashbase": "0x08000000",
                "flashsize": "0x10000",
                "algorithm": "MAIN.FLM",
            }],
        }}}
    }

    manifest = resources_module.build_bundle_from_resources(
        {
            "resources/algorithms/chips_cn.json": json.dumps(catalog).encode(),
            "resources/algorithms/MAIN.FLM": b"main",
        },
        tmp_path / "bundle",
        source_sha256="c" * 64,
        source_version="0.0.21",
    )

    assert manifest["target_count"] == 1
    assert manifest["targets"][0]["option_algorithm"] is None
    assert manifest["missing_references"] == ["MISSING-OPTION.FLM"]
    assert manifest["missing_reference_count"] == 1
    assert manifest["skipped_target_count"] == 0
    assert manifest["source"]["version"] == "0.0.21"


def test_build_bundle_skips_target_with_missing_program_algorithm(
    resources_module, tmp_path
):
    catalog = {
        "Vendor": {"Family": {
            "GOOD": {
                "rambase": "0x20000000",
                "ramsize": "0x1000",
                "algoprog": [{
                    "flashbase": "0x08000000",
                    "flashsize": "0x10000",
                    "algorithm": "MAIN.FLM",
                }],
            },
            "BAD": {
                "rambase": "0x20000000",
                "ramsize": "0x1000",
                "algoprog": [{
                    "flashbase": "0x08000000",
                    "flashsize": "0x10000",
                    "algorithm": "MISSING-MAIN.FLM",
                }],
            },
        }}
    }

    manifest = resources_module.build_bundle_from_resources(
        {
            "resources/chips.json": json.dumps(catalog).encode(),
            "resources/algorithms/MAIN.FLM": b"main",
        },
        tmp_path / "bundle",
        source_sha256="d" * 64,
    )

    assert manifest["target_count"] == 1
    assert manifest["targets"][0]["part_number"] == "GOOD"
    assert manifest["missing_references"] == ["MISSING-MAIN.FLM"]
    assert manifest["skipped_target_count"] == 1


def test_pinned_daplinkutility_executable_builds_expected_complete_bundle(
    resources_module, tmp_path
):
    source = os.environ.get("MKLINK_DAPLINKUTILITY_EXE", "").strip()
    if not source:
        pytest.skip("MKLINK_DAPLINKUTILITY_EXE is not configured")

    manifest = resources_module.build_bundle(Path(source), tmp_path / "bundle")
    digest = hashlib.sha256(Path(source).read_bytes()).hexdigest()

    expected = {
        resources_module.SUPPORTED_SOURCE_SHA256: {
            "manufacturer_count": 45,
            "series_count": 502,
            "target_count": 8137,
            "region_count": 12161,
            "referenced_algorithm_count": 1468,
            "blob_count": 1428,
            "missing_reference_count": 0,
            "missing_references": [],
            "skipped_target_count": 0,
        },
        resources_module.RELEASE_SOURCE_SHA256: {
            "manufacturer_count": 94,
            "series_count": 660,
            "target_count": 7059,
            "region_count": 9236,
            "referenced_algorithm_count": 2288,
            "blob_count": 2224,
            "missing_reference_count": 3,
            "missing_references": [
                "HVC5xxxx_OPT.FLM",
                "S32K116_OPT.FLM",
                "S32K118_OPT.FLM",
            ],
            "skipped_target_count": 0,
        },
    }
    assert digest in resources_module.SUPPORTED_SOURCES
    assert manifest["source"]["sha256"] == digest
    assert manifest["source"]["version"] == resources_module.SUPPORTED_SOURCES[digest][0]
    for key, value in expected.get(digest, {}).items():
        assert manifest[key] == value
