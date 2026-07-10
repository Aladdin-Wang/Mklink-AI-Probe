"""Search installed and cached CMSIS-Pack targets without hardware access."""

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from .models import TargetRecord
from .paths import PackPaths


@dataclass(frozen=True)
class PackCatalogStatus:
    last_error: Optional[str]
    index_available: bool
    target_count: int


def _production_builtin_provider() -> Iterable[TargetRecord]:
    """Load pyOCD's builtin target registry only when builtin targets are needed."""

    from pyocd.target import TARGET

    if hasattr(TARGET, "items"):
        entries = TARGET.items()
    else:
        names = TARGET.get_all_target_names()
        entries = ((name, TARGET[name]) for name in names)

    records = []
    for name, target_type in entries:
        part_number = getattr(target_type, "PART_NUMBER", None) or name
        vendor = getattr(target_type, "VENDOR", "") or ""
        records.append(
            TargetRecord(
                part_number=str(part_number),
                vendor=str(vendor),
                installed=True,
                source="builtin",
            )
        )
    return records


class PackCatalog:
    """Merged view of pyOCD builtin targets and the last cached pack index."""

    def __init__(
        self,
        paths: PackPaths,
        builtin_provider: Callable[[], Iterable[TargetRecord]] = _production_builtin_provider,
    ) -> None:
        self._paths = paths
        self._builtin_provider = builtin_provider
        self._builtin_records = None  # type: Optional[List[TargetRecord]]
        self._refresh_error = None  # type: Optional[str]
        self._refresh_error_signature = None  # type: Optional[Tuple[int, int]]
        self._index_error = None  # type: Optional[str]
        self._state_error = None  # type: Optional[str]
        self._index_available = False
        self._index_loaded = False
        self._index_signature = None  # type: Optional[Tuple[int, int]]
        self._index_records = []  # type: List[TargetRecord]
        self._state_loaded = False
        self._state_signature = None  # type: Optional[Tuple[int, int]]
        self._installed_paths = {}  # type: Dict[Tuple[str, str], str]
        self._target_count = 0

    def note_refresh_failure(self, error: object) -> None:
        """Record a refresh failure without modifying the last-good index."""

        self._refresh_error = str(error)
        self._refresh_error_signature = self._file_signature(self._paths.index_file)

    def status(self) -> PackCatalogStatus:
        return PackCatalogStatus(
            last_error=self._refresh_error or self._index_error or self._state_error,
            index_available=self._index_available,
            target_count=self._target_count,
        )

    def search(
        self,
        query: str,
        vendor: Optional[str] = None,
        installed: Optional[bool] = None,
        limit: int = 100,
    ) -> List[TargetRecord]:
        if limit <= 0:
            return []

        if self._builtin_records is None:
            self._builtin_records = list(self._builtin_provider())
        builtin_records = self._builtin_records
        cached_records = self._read_cached_records()
        installed_paths = self._read_installed_paths()
        cached_records = [
            self._apply_installed_path(record, installed_paths)
            for record in cached_records
        ]
        records = self._merge_records(builtin_records, cached_records)
        self._target_count = len(records)

        needle = query.casefold().strip()
        vendor_key = vendor.casefold().strip() if vendor is not None else None
        matches = [
            record
            for record in records
            if needle in record.part_number.casefold()
            and (vendor_key is None or record.vendor.casefold() == vendor_key)
            and (installed is None or record.installed is installed)
        ]
        matches.sort(key=lambda record: (record.part_number.casefold(), record.pack_id or ""))
        return matches[:limit]

    def _read_cached_records(self) -> List[TargetRecord]:
        signature = self._file_signature(self._paths.index_file)
        if self._index_loaded and signature == self._index_signature:
            return self._index_records

        if signature is None:
            self._index_error = "cached pack index unavailable: file does not exist"
            return self._index_records

        try:
            with self._paths.index_file.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            records = self._parse_index(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._index_error = "cached pack index unavailable: {}".format(error)
            return self._index_records

        self._index_available = True
        self._index_loaded = True
        self._index_signature = signature
        self._index_error = None
        self._index_records = records
        if (
            self._refresh_error is not None
            and signature != self._refresh_error_signature
        ):
            self._refresh_error = None
            self._refresh_error_signature = None
        return self._index_records

    def _read_installed_paths(self) -> Dict[Tuple[str, str], str]:
        signature = self._file_signature(self._paths.state_file)
        if self._state_loaded and signature == self._state_signature:
            return self._installed_paths

        if signature is None:
            self._state_error = (
                "installed pack state unavailable: file does not exist"
                if self._state_loaded
                else None
            )
            return self._installed_paths

        try:
            with self._paths.state_file.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._state_error = "installed pack state unavailable: {}".format(error)
            return self._installed_paths

        installed = payload.get("installed") if isinstance(payload, Mapping) else None
        if not isinstance(installed, Mapping):
            self._state_error = "installed pack state must contain an installed mapping"
            return self._installed_paths

        paths = {}
        for pack_id, versions in installed.items():
            if not isinstance(versions, Mapping):
                continue
            for version, pack_path in versions.items():
                if isinstance(pack_path, str):
                    paths[(str(pack_id), str(version))] = pack_path
        self._state_loaded = True
        self._state_signature = signature
        self._state_error = None
        self._installed_paths = paths
        return self._installed_paths

    @staticmethod
    def _file_signature(path: Path) -> Optional[Tuple[int, int]]:
        try:
            stat = path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _apply_installed_path(
        record: TargetRecord,
        installed_paths: Mapping[Tuple[str, str], str],
    ) -> TargetRecord:
        if record.pack_id is None or record.pack_version is None:
            return record
        pack_path = installed_paths.get((record.pack_id, record.pack_version))
        if pack_path is None or not Path(pack_path).is_file():
            return record
        return replace(record, installed=True, pack_path=pack_path)

    @classmethod
    def _parse_index(cls, payload: object) -> List[TargetRecord]:
        if not isinstance(payload, Mapping):
            raise ValueError("cached pack index must be a mapping")

        candidates = payload
        for container_name in ("targets", "devices"):
            container = payload.get(container_name)
            if isinstance(container, Mapping):
                candidates = container
                break

        records = []
        for part_number, details in candidates.items():
            if not isinstance(details, Mapping):
                continue
            records.append(cls._record_from_index(str(part_number), details))
        return records

    @staticmethod
    def _record_from_index(part_number: str, details: Mapping) -> TargetRecord:
        pack_details = details.get("from_pack")
        if not isinstance(pack_details, Mapping):
            pack_details = {}

        vendor = pack_details.get("vendor") or details.get("vendor") or ""
        pack_name = (
            pack_details.get("pack")
            or pack_details.get("name")
            or details.get("pack")
            or ""
        )
        version = pack_details.get("version") or details.get("version")
        explicit_pack_id = details.get("pack_id")

        if explicit_pack_id:
            pack_id = str(explicit_pack_id)
        elif pack_name and vendor:
            prefix = "{}.".format(vendor)
            pack_text = str(pack_name)
            pack_id = pack_text if pack_text.casefold().startswith(prefix.casefold()) else prefix + pack_text
        elif pack_name:
            pack_id = str(pack_name)
        else:
            pack_id = None

        return TargetRecord(
            part_number=part_number,
            vendor=str(vendor),
            pack_id=pack_id,
            pack_version=str(version) if version is not None else None,
            installed=False,
            source="index",
        )

    @staticmethod
    def _merge_records(
        builtin_records: Iterable[TargetRecord],
        cached_records: Iterable[TargetRecord],
    ) -> List[TargetRecord]:
        selected = {}  # type: Dict[str, TargetRecord]
        for record in list(builtin_records) + list(cached_records):
            key = record.part_number.casefold()
            current = selected.get(key)
            if current is None or PackCatalog._priority(record) > PackCatalog._priority(current):
                selected[key] = record
        return list(selected.values())

    @staticmethod
    def _priority(record: TargetRecord) -> Tuple[bool, bool]:
        return record.installed, record.source == "builtin"
