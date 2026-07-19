import importlib.util
import json
import sys
from pathlib import Path

import pytest


COVERAGE_PATH = (
    Path(__file__).resolve().parents[3]
    / "skills"
    / "tauri-gui-builder"
    / "scripts"
    / "daplink_coverage.py"
)


@pytest.fixture
def coverage_module():
    spec = importlib.util.spec_from_file_location("mklink_daplink_coverage", COVERAGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_catalog():
    return {
        "VendorA": {
            "Family A": {
                "PART-A": {
                    "rambase": "0x20000000",
                    "ramsize": "0x1000",
                    "algooptb": "PART_OPT.FLM",
                    "algoprog": [
                        {
                            "flashbase": "0x08000000",
                            "flashsize": "0x10000",
                            "algorithm": "PART_MAIN.FLM",
                        },
                        {
                            "flashbase": "0x90000000",
                            "flashsize": "0x800000",
                            "algorithm": "PART_EXT.FLM",
                        },
                    ],
                    "builtin": True,
                },
                "PART.B": {
                    "rambase": "0x20001000",
                    "ramsize": "0x2000",
                    "algoprog": [
                        {
                            "flashbase": "0x00000000",
                            "flashsize": "0x20000",
                            "algorithm": "PART_B.FLM",
                        }
                    ],
                    "builtin": True,
                },
            }
        }
    }


def test_parse_catalog_preserves_models_regions_and_external_flash(coverage_module):
    targets = coverage_module.parse_catalog(sample_catalog())

    assert [target.model for target in targets] == ["PART-A", "PART.B"]
    assert targets[0].manufacturer == "VendorA"
    assert targets[0].series == "Family A"
    assert targets[0].ram_base == 0x20000000
    assert targets[0].ram_size == 0x1000
    assert targets[0].option_algorithm == "PART_OPT.FLM"
    assert [(region.flash_start, region.flash_size, region.algorithm) for region in targets[0].regions] == [
        (0x08000000, 0x10000, "PART_MAIN.FLM"),
        (0x90000000, 0x800000, "PART_EXT.FLM"),
    ]


def test_compare_coverage_prefers_exact_then_unique_conservative_alias(coverage_module):
    targets = coverage_module.parse_catalog(sample_catalog())
    sources = (
        coverage_module.CoverageSource("licensed-builtin-pack", ("PART-A",)),
        coverage_module.CoverageSource("pyocd-builtin", ("part_b",)),
        coverage_module.CoverageSource("hpm-rom-api", ("HPM5300",)),
    )

    report = coverage_module.compare_coverage(targets, sources)

    assert report.counts == {"alias": 1, "exact": 1}
    assert report.matches[0].status == "exact"
    assert report.matches[0].source == "licensed-builtin-pack"
    assert report.matches[1].status == "alias"
    assert report.matches[1].source == "pyocd-builtin"
    assert report.matches[1].matched_model == "part_b"


def test_compare_coverage_does_not_guess_ambiguous_or_similar_models(coverage_module):
    targets = coverage_module.parse_catalog(sample_catalog())
    sources = (
        coverage_module.CoverageSource("licensed-builtin-pack", ("PART_A", "PART.A")),
        coverage_module.CoverageSource("pyocd-builtin", ("PART",)),
    )

    report = coverage_module.compare_coverage(targets, sources)

    assert report.counts == {"unresolved": 2}
    assert all(match.matched_model is None for match in report.matches)


def test_flm_hashes_are_identification_evidence_not_redistribution_permission(
    coverage_module,
):
    targets = coverage_module.parse_catalog(sample_catalog())
    report = coverage_module.compare_coverage(
        targets,
        (),
        algorithm_hashes={
            "part_main.flm": "a" * 64,
            "PART_EXT.FLM": "b" * 64,
        },
    )

    assert report.matches[0].algorithm_evidence == (
        coverage_module.AlgorithmEvidence("PART_MAIN.FLM", "a" * 64, False),
        coverage_module.AlgorithmEvidence("PART_EXT.FLM", "b" * 64, False),
    )


def test_cli_writes_path_free_aggregate_report(coverage_module, tmp_path, monkeypatch):
    chips = tmp_path / "chips.json"
    chips.write_text(json.dumps(sample_catalog()), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "packs": [{
                "targets": [{"part_number": "PART-A", "vendor": "VendorA"}],
            }],
        }),
        encoding="utf-8",
    )
    hashes = tmp_path / "flm-hashes.json"
    hashes.write_text(
        json.dumps([{"algorithm": "PART_MAIN.FLM", "sha256": "c" * 64}]),
        encoding="utf-8",
    )
    output = tmp_path / "coverage.json"
    monkeypatch.setattr(coverage_module, "pyocd_builtin_models", lambda: ("part_b",))
    monkeypatch.setattr(coverage_module, "hpm_rom_models", lambda: ("HPM5300",))

    result = coverage_module.main([
        "--chips", str(chips),
        "--builtin-manifest", str(manifest),
        "--flm-hashes", str(hashes),
        "--json-out", str(output),
    ])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["counts"] == {"alias": 1, "exact": 1}
    assert payload["manufacturer_count"] == 1
    assert payload["series_count"] == 1
    assert payload["model_count"] == 2
    assert payload["source_counts"] == {
        "licensed-builtin-pack": 1,
        "pyocd-builtin": 1,
    }
    assert str(tmp_path) not in output.read_text(encoding="utf-8")
