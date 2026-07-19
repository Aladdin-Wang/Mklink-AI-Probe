#!/usr/bin/env python3
"""Compare DAPLinkUtility model metadata with redistributable target sources."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import re
from typing import Dict, Iterable, Mapping, Sequence, Tuple


_SEPARATORS = re.compile(r"[-_./\s]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class DapRegion:
    flash_start: int
    flash_size: int
    algorithm: str


@dataclass(frozen=True)
class DapTarget:
    manufacturer: str
    series: str
    model: str
    ram_base: int
    ram_size: int
    option_algorithm: str
    regions: Tuple[DapRegion, ...]


@dataclass(frozen=True)
class CoverageModel:
    model: str
    manufacturer: str


@dataclass(frozen=True)
class CoverageSource:
    name: str
    models: Tuple[CoverageModel, ...]


@dataclass(frozen=True)
class AlgorithmEvidence:
    algorithm: str
    sha256: str
    redistributable: bool = False


@dataclass(frozen=True)
class CoverageMatch:
    target: DapTarget
    status: str
    source: str | None
    matched_model: str | None
    algorithm_evidence: Tuple[AlgorithmEvidence, ...]


@dataclass(frozen=True)
class CoverageReport:
    matches: Tuple[CoverageMatch, ...]

    @property
    def counts(self) -> Dict[str, int]:
        return dict(sorted(Counter(match.status for match in self.matches).items()))

    @property
    def source_counts(self) -> Dict[str, int]:
        return dict(sorted(Counter(
            match.source for match in self.matches if match.source is not None
        ).items()))


def _text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(description))
    return value.strip()


def _address(value: object, description: str) -> int:
    if isinstance(value, bool):
        raise ValueError("{} must be an integer".format(description))
    try:
        result = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("{} must be an integer".format(description)) from error
    if not 0 <= result <= 0xFFFFFFFF:
        raise ValueError("{} must fit in 32 bits".format(description))
    return result


def normalize_model(value: str) -> str:
    """Remove only common model-name separators and case differences."""
    return _SEPARATORS.sub("", str(value).strip().casefold())


_MANUFACTURER_ALIASES = {
    "stm32": "stmicroelectronics",
    "st": "stmicroelectronics",
    "nrf": "nordicsemiconductor",
    "nordic": "nordicsemiconductor",
    "nordicsemiconductorasa": "nordicsemiconductor",
    "numicro": "nuvoton",
    "nuvotontechnology": "nuvoton",
    "mircochip": "microchip",
}


def normalize_manufacturer(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value).strip().casefold())
    return _MANUFACTURER_ALIASES.get(normalized, normalized)


def _algorithm_name(value: object) -> str:
    text = _text(value, "algorithm").replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or len(path.parts) != 1 or ":" in text or text in (".", ".."):
        raise ValueError("algorithm must be a safe resource name")
    return text


def _region_value(region: Mapping[str, object], current: str, legacy: str) -> object:
    return region[current] if current in region else region.get(legacy)


def parse_catalog(payload: object) -> Tuple[DapTarget, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("DAPLinkUtility catalog must be an object")
    targets = []
    for raw_manufacturer, raw_series in payload.items():
        manufacturer = _text(raw_manufacturer, "manufacturer")
        if not isinstance(raw_series, Mapping):
            raise ValueError("manufacturer series must be an object")
        for raw_series_name, raw_models in raw_series.items():
            series = _text(raw_series_name, "series")
            if not isinstance(raw_models, Mapping):
                raise ValueError("series models must be an object")
            for raw_model, raw_target in raw_models.items():
                model = _text(raw_model, "model")
                if not isinstance(raw_target, Mapping):
                    raise ValueError("model metadata must be an object")
                raw_regions = raw_target.get("algoprog")
                if not isinstance(raw_regions, list) or not raw_regions:
                    raise ValueError("model algoprog must be a non-empty list")
                regions = []
                for raw_region in raw_regions:
                    if not isinstance(raw_region, Mapping):
                        raise ValueError("algoprog entries must be objects")
                    regions.append(DapRegion(
                        flash_start=_address(
                            _region_value(raw_region, "flashbase", "addr"), "flashbase"
                        ),
                        flash_size=_address(
                            _region_value(raw_region, "flashsize", "size"), "flashsize"
                        ),
                        algorithm=_algorithm_name(
                            _region_value(raw_region, "algorithm", "algo")
                        ),
                    ))
                raw_option = str(raw_target.get("algooptb") or "").strip()
                targets.append(DapTarget(
                    manufacturer=manufacturer,
                    series=series,
                    model=model,
                    ram_base=_address(raw_target.get("rambase"), "rambase"),
                    ram_size=_address(raw_target.get("ramsize"), "ramsize"),
                    option_algorithm=_algorithm_name(raw_option) if raw_option else "",
                    regions=tuple(regions),
                ))
    return tuple(sorted(
        targets,
        key=lambda target: (
            target.manufacturer.casefold(),
            target.series.casefold(),
            target.model.casefold(),
        ),
    ))


def _algorithm_evidence(
    target: DapTarget,
    hashes: Mapping[str, str],
) -> Tuple[AlgorithmEvidence, ...]:
    names = [region.algorithm for region in target.regions]
    if target.option_algorithm:
        names.append(target.option_algorithm)
    evidence = []
    seen = set()
    for name in names:
        key = Path(name.replace("\\", "/")).name.casefold()
        digest = hashes.get(key)
        if digest is None or key in seen:
            continue
        seen.add(key)
        evidence.append(AlgorithmEvidence(name, digest, False))
    return tuple(evidence)


def compare_coverage(
    targets: Iterable[DapTarget],
    sources: Sequence[CoverageSource],
    *,
    algorithm_hashes: Mapping[str, str] | None = None,
) -> CoverageReport:
    prepared = []
    aliases: Dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    for source_index, source in enumerate(sources):
        name = _text(source.name, "coverage source name")
        models = tuple(sorted({
            CoverageModel(
                _text(model.model, "coverage model"),
                _text(model.manufacturer, "coverage manufacturer"),
            )
            for model in source.models
        }, key=lambda model: (model.manufacturer.casefold(), model.model.casefold())))
        exact = {
            (normalize_manufacturer(model.manufacturer), model.model.casefold()): model.model
            for model in models
        }
        prepared.append((name, exact))
        for model in models:
            aliases.setdefault((
                normalize_manufacturer(model.manufacturer), normalize_model(model.model)
            ), []).append(
                (source_index, name, model.model)
            )

    hashes = {
        Path(str(name).replace("\\", "/")).name.casefold(): str(digest).casefold()
        for name, digest in (algorithm_hashes or {}).items()
        if _SHA256.fullmatch(str(digest).casefold()) is not None
    }
    matches = []
    for target in targets:
        manufacturer = normalize_manufacturer(target.manufacturer)
        matched_status = "unresolved"
        matched_source = None
        matched_model = None
        for source_name, exact in prepared:
            candidate = exact.get((manufacturer, target.model.casefold()))
            if candidate is not None:
                matched_status = "exact"
                matched_source = source_name
                matched_model = candidate
                break
        if matched_model is None:
            candidates = aliases.get((manufacturer, normalize_model(target.model)), [])
            distinct_models = {candidate[2].casefold() for candidate in candidates}
            if len(distinct_models) == 1 and candidates:
                _index, matched_source, matched_model = min(
                    candidates, key=lambda candidate: candidate[0]
                )
                matched_status = "alias"
        matches.append(CoverageMatch(
            target=target,
            status=matched_status,
            source=matched_source,
            matched_model=matched_model,
            algorithm_evidence=_algorithm_evidence(target, hashes),
        ))
    return CoverageReport(tuple(matches))


def load_manifest_models(path: Path) -> Tuple[CoverageModel, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    packs = payload.get("packs") if isinstance(payload, Mapping) else None
    if not isinstance(packs, list):
        raise ValueError("builtin manifest must contain a packs list")
    models = set()
    for pack in packs:
        targets = pack.get("targets") if isinstance(pack, Mapping) else None
        if not isinstance(targets, list):
            raise ValueError("builtin manifest Pack must contain targets")
        for target in targets:
            if not isinstance(target, Mapping):
                raise ValueError("builtin manifest target must be an object")
            models.add(CoverageModel(
                _text(target.get("part_number"), "builtin part number"),
                _text(target.get("vendor"), "builtin vendor"),
            ))
    return tuple(sorted(
        models, key=lambda model: (model.manufacturer.casefold(), model.model.casefold())
    ))


def load_algorithm_hashes(path: Path) -> Dict[str, str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        records = payload.get("records", payload.get("algorithms", payload))
    else:
        records = payload
    if isinstance(records, Mapping):
        items = records.items()
    elif isinstance(records, list):
        items = []
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("FLM hash records must be objects")
            name = record.get("algorithm", record.get("name", record.get("file_name")))
            items.append((name, record.get("sha256")))
    else:
        raise ValueError("FLM hash inventory must be an object or list")
    hashes = {}
    for raw_name, raw_digest in items:
        name = Path(_text(raw_name, "FLM name").replace("\\", "/")).name.casefold()
        digest = _text(raw_digest, "FLM SHA-256").casefold()
        if _SHA256.fullmatch(digest) is None:
            raise ValueError("FLM SHA-256 must contain 64 hexadecimal characters")
        previous = hashes.get(name)
        if previous is not None and previous != digest:
            raise ValueError("conflicting FLM SHA-256 values for the same basename")
        hashes[name] = digest
    return hashes


def pyocd_builtin_models() -> Tuple[CoverageModel, ...]:
    from pyocd.target import TARGET

    models = {
        CoverageModel(
            str(getattr(target_type, "PART_NUMBER", None) or name),
            str(getattr(target_type, "VENDOR", None) or "pyOCD"),
        )
        for name, target_type in TARGET.items()
    }
    return tuple(sorted(
        models, key=lambda model: (model.manufacturer.casefold(), model.model.casefold())
    ))


def hpm_rom_models() -> Tuple[CoverageModel, ...]:
    from mklink.hpm_config import HPM_ROM_TARGETS

    return tuple(CoverageModel(model, "HPMicro") for model in HPM_ROM_TARGETS)


def _match_dict(match: CoverageMatch) -> Dict[str, object]:
    return {
        "manufacturer": match.target.manufacturer,
        "series": match.target.series,
        "model": match.target.model,
        "status": match.status,
        "source": match.source,
        "matched_model": match.matched_model,
        "ram_base": match.target.ram_base,
        "ram_size": match.target.ram_size,
        "option_algorithm": match.target.option_algorithm,
        "regions": [asdict(region) for region in match.target.regions],
        "algorithm_evidence": [asdict(record) for record in match.algorithm_evidence],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chips", type=Path, required=True)
    parser.add_argument("--builtin-manifest", type=Path, required=True)
    parser.add_argument("--flm-hashes", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    targets = parse_catalog(json.loads(args.chips.read_text(encoding="utf-8")))
    hashes = load_algorithm_hashes(args.flm_hashes) if args.flm_hashes else {}
    sources = (
        CoverageSource("licensed-builtin-pack", load_manifest_models(args.builtin_manifest)),
        CoverageSource("pyocd-builtin", pyocd_builtin_models()),
        CoverageSource("hpm-rom-api", hpm_rom_models()),
    )
    report = compare_coverage(targets, sources, algorithm_hashes=hashes)
    payload = {
        "schema": 1,
        "manufacturer_count": len({target.manufacturer for target in targets}),
        "series_count": len({(target.manufacturer, target.series) for target in targets}),
        "model_count": len(targets),
        "counts": report.counts,
        "source_counts": report.source_counts,
        "algorithm_hash_count": len(hashes),
        "matches": [_match_dict(match) for match in report.matches],
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
