"""CMSIS-Pack device/SVD selection and read-only peripheral watch items."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

from mklink.superwatch import WatchItem

MAX_XML_BYTES = 32 * 1024 * 1024


def _xml(data: bytes):
    if (
        len(data) > MAX_XML_BYTES
        or b"<!DOCTYPE" in data.upper()
        or b"<!ENTITY" in data.upper()
    ):
        raise ValueError("Unsupported or oversized Pack XML")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"Invalid Pack/SVD XML: {error}") from error
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    return root


def _member(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in str(path):
        raise ValueError("SVD path must stay inside its Pack")
    return str(path)


@dataclass(frozen=True)
class SvdTarget:
    target: str
    pack: str
    source: Path
    svd: str
    archive: bool = False

    @property
    def key(self) -> str:
        return hashlib.sha256(
            f"{self.source}|{self.target}|{self.svd}".encode()
        ).hexdigest()[:24]

    def public(self) -> dict:
        return {
            "id": self.key,
            "target": self.target,
            "pack": self.pack,
            "svd": self.svd,
        }

    def read(self) -> bytes:
        member = _member(self.svd)
        if self.archive:
            with ZipFile(self.source) as archive:
                if archive.getinfo(member).file_size > MAX_XML_BYTES:
                    raise ValueError("SVD is too large")
                return archive.read(member)
        root = self.source.parent.resolve()
        path = (root / member).resolve()
        path.relative_to(root)
        if path.stat().st_size > MAX_XML_BYTES:
            raise ValueError("SVD is too large")
        return path.read_bytes()


def pdsc_targets(
    data: bytes, source: Path, *, archive: bool = False
) -> list[SvdTarget]:
    root = _xml(data)
    pack = f"{root.findtext('vendor', '')}.{root.findtext('name', '')}"
    version = root.find("./releases/release")
    if version is not None:
        pack += "@" + version.get("version", "")
    results = []

    def visit(element, inherited_svd=""):
        svd = inherited_svd
        for debug in element.findall("debug"):
            if debug.get("svd"):
                svd = debug.get("svd")
                break
        target = element.get("Dvariant") or element.get("Dname")
        if target and svd:
            try:
                results.append(SvdTarget(target, pack, source, _member(svd), archive))
            except ValueError:
                pass
        for child in element:
            if child.tag in {"devices", "family", "subFamily", "device", "variant"}:
                visit(child, svd)

    visit(root)
    return results


def discover_svd_targets(project_root: str) -> list[SvdTarget]:
    """Inspect installed Packs only; never download or guess SVD filenames."""
    from mklink.project_config import load_project_info
    from mklink.cmsis_dap.paths import PackPaths
    from mklink.cmsis_dap.algorithm_catalog import _installed_pack_records
    from mklink.cmsis_dap.builtin_pack_bundle import load_builtin_pack_records

    info = load_project_info(project_root) or {}
    roots = {Path.home() / "AppData/Local/Arm/Packs", Path.home() / ".cache/arm/packs"}
    for name in ("CMSIS_PACK_ROOT", "ARM_PACK_ROOT"):
        if os.environ.get(name):
            roots.add(Path(os.environ[name]))
    flm = info.get("flm_path")
    descriptors = set()
    if flm:
        for parent in list(Path(flm).parents)[:4]:
            matches = list(parent.glob("*.pdsc"))
            if matches:
                descriptors.update(matches)
                if len(parent.parents) >= 3:
                    roots.add(parent.parents[2])
                break
    for root in roots:
        if root.is_dir():
            descriptors.update(root.glob("*/*/*/*.pdsc"))
    targets = []
    for descriptor in sorted(descriptors):
        try:
            if descriptor.stat().st_size <= MAX_XML_BYTES:
                targets.extend(pdsc_targets(descriptor.read_bytes(), descriptor))
        except (OSError, ValueError, ET.ParseError):
            continue
    records = _installed_pack_records(PackPaths(), "")
    records.extend(load_builtin_pack_records())
    archive_members = {}
    for source in {Path(record.pack_path) for record in records if record.pack_path}:
        try:
            with ZipFile(source) as archive:
                archive_members[source] = set(archive.namelist())
                for item in archive.infolist():
                    if (
                        item.filename.endswith(".pdsc")
                        and item.file_size <= MAX_XML_BYTES
                    ):
                        targets.extend(
                            pdsc_targets(archive.read(item), source, archive=True)
                        )
        except (OSError, ValueError, ET.ParseError, BadZipFile):
            continue
    available = [
        target
        for target in targets
        if (
            target.svd in archive_members.get(target.source, set())
            if target.archive
            else (target.source.parent / target.svd).is_file()
        )
    ]
    unique = {}
    for target in available:
        unique.setdefault((target.target, target.pack, target.svd), target)
    return sorted(unique.values(), key=lambda t: (t.target, t.pack))


@lru_cache(maxsize=2)
def svd_watch_items(data: bytes) -> tuple[dict[str, WatchItem], int]:
    from .cmsis_dap.pyocd_runtime import import_pyocd_module

    SVDParser = import_pyocd_module("pyocd.debug.svd.parser").SVDParser

    root = _xml(data)
    from .svd_normalize import normalize, integer

    root = normalize(root)
    if integer(root.findtext("addressUnitBits", "8")) != 8:
        raise ValueError("Only byte-addressed peripherals are supported")
    if root.findtext("./cpu/endian", "little") != "little":
        raise ValueError("Only little-endian peripheral access is supported")
    device = SVDParser.for_xml_file(
        io.BytesIO(ET.tostring(root)), remove_reserved=True
    ).get_device()
    items = {}
    skipped = 0
    for peripheral in device.peripherals:
        for register in peripheral.registers or []:
            fields = register.fields or []
            width = register.size
            description = " ".join(
                [register.description or "", *(f.description or "" for f in fields)]
            )
            # Current dump/read_ram transports cannot promise an atomic halfword
            # transaction. Never widen a narrow MMIO read into its neighbours.
            if (
                width != 32
                or register.access not in ("read-only", "read-write", "read-writeOnce")
                or register.read_action
                or any(field.read_action for field in fields)
                or (
                    fields
                    and all(f.access in ("write-only", "writeOnce") for f in fields)
                )
                or register.alternate_group
                or re.search(
                    r"(?i)read.{0,80}(clear|pop)|clear.{0,80}read",
                    re.sub(r"\s+", " ", description),
                )
                or (
                    peripheral.name.upper().startswith(("SYST", "SYSTICK"))
                    and register.name.upper() in ("CSR", "CTRL")
                )
            ):
                skipped += 1
                continue
            address = peripheral.base_address + register.address_offset
            # Cortex-M SysTick COUNTFLAG and DHCSR sticky status clear on read.
            if address in (0xE000E010, 0xE000EDF0):
                skipped += 1
                continue
            if not 0 <= address <= 0xFFFFFFFF - width // 8 + 1 or address % (
                width // 8
            ):
                skipped += 1
                continue
            name = f"{peripheral.name}.{register.name}"
            metadata = {
                "writable": False,
                "register": name,
                "description": register.description or "",
            }
            items[name] = WatchItem(
                name,
                address,
                f"uint{width}_t",
                width // 8,
                source="peripheral",
                scalar_kind="unsigned",
                metadata=metadata,
            )
            for field in fields:
                offset, bits = field.bit_offset, field.bit_width
                if (
                    not isinstance(bits, int)
                    or not isinstance(offset, int)
                    or bits <= 0
                    or offset < 0
                    or offset + bits > width
                    or field.access in ("write-only", "writeOnce")
                ):
                    continue
                field_name = f"{name}.{field.name}"
                field_meta = {
                    **metadata,
                    "bit_offset": offset,
                    "bit_width": bits,
                    "description": field.description or "",
                }
                items[field_name] = WatchItem(
                    field_name,
                    address,
                    "bool" if bits == 1 else f"uint{width}_t",
                    width // 8,
                    source="peripheral",
                    scalar_kind="unsigned",
                    metadata=field_meta,
                )
                if (
                    re.fullmatch(r"GPIO[A-Z]", peripheral.name)
                    and register.name == "IDR"
                    and bits == 1
                ):
                    alias = f"{peripheral.name}.{offset}"
                    items[alias] = WatchItem(
                        alias,
                        address,
                        "bool",
                        width // 8,
                        source="peripheral",
                        scalar_kind="unsigned",
                        metadata=field_meta,
                    )
    return items, skipped


@dataclass
class PeripheralCatalog:
    selection: dict
    items: dict[str, WatchItem]
    skipped: int = 0

    def resolve(self, name: str) -> WatchItem:
        key = name.strip().replace("->", ".").casefold()
        matches = [item for n, item in self.items.items() if n.casefold() == key]
        if len(matches) != 1:
            raise KeyError(f"Unknown, ambiguous or excluded peripheral: {name}")
        return matches[0]

    def public(self, query: str = "") -> dict:
        from .superwatch import make_channel_metadata

        items = [
            i for i in self.items.values() if query.casefold() in i.name.casefold()
        ]
        metadata = make_channel_metadata(items)
        return {
            "selection": {**self.selection, "skipped_registers": self.skipped},
            "items": [{"name": i.name, **metadata[i.name]} for i in items],
        }


def load_catalog(project_root=".", *, target_id=None, chip=None, svd=None, target=None):
    """Explicit selection, or restore the same project selection for every UI."""
    import json

    selectors = sum(bool(x) for x in (target_id, chip, svd, target))
    if selectors > 1:
        raise ValueError("Choose only one of target_id, chip or svd")
    if not selectors:
        path = Path(project_root) / ".mklink/peripheral-selection.json"
        if not path.is_file():
            return None
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or set(saved) not in ({"target_id"}, {"svd"}):
            raise ValueError("Invalid saved peripheral selection")
        if not all(isinstance(v, str) and v for v in saved.values()):
            raise ValueError("Empty saved peripheral selection")
        return load_catalog(project_root, **saved)
    if svd:
        path = Path(svd).expanduser().resolve()
        if path.stat().st_size > MAX_XML_BYTES:
            raise ValueError("SVD is too large")
        data = path.read_bytes()
        selection = {
            "target": _xml(data).findtext("name", ""),
            "svd": str(path),
            "pack": "local",
            "id": None,
        }
    else:
        if target is None:
            targets = discover_svd_targets(project_root)
            matches = (
                [t for t in targets if t.key == target_id]
                if target_id
                else [t for t in targets if t.target.casefold() == chip.casefold()]
            )
            if len(matches) != 1:
                raise ValueError(
                    "Select an exact target_id: chip is missing or has multiple Packs"
                )
            target = matches[0]
        data = target.read()
        selection = target.public()
    items, skipped = svd_watch_items(data)
    if not items:
        raise ValueError(
            "Selected SVD has no supported, side-effect-free 32-bit registers"
        )
    return PeripheralCatalog(selection, items, skipped)


def save_catalog_selection(project_root, catalog):
    import json

    # Only the description selection is shared; no target state or firmware path.
    path = Path(project_root) / ".mklink/peripheral-selection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    choice = (
        {"target_id": catalog.selection["id"]}
        if catalog.selection.get("id")
        else {"svd": catalog.selection["svd"]}
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(choice), encoding="utf-8")
    temporary.replace(path)


def read_item(device, item):
    if item.size != 4 or item.address % 4:
        raise ValueError(
            "Exact aligned 32-bit MMIO access required by current transport"
        )
    data = device.read_memory(item.address, item.size)
    if len(data) != item.size:
        raise RuntimeError(f"Incomplete register read: {item.name}")
    value = int.from_bytes(data, "little")
    if "bit_width" in item.metadata:
        value = (value >> item.metadata["bit_offset"]) & (
            (1 << item.metadata["bit_width"]) - 1
        )
    return value


def capture_items(device, items, *, duration=1.0, period=0.01):
    import math, time
    from .dump_memory import DumpMemoryStreamSession
    from .superwatch import build_read_blocks, compile_frame_decoder

    if not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError("duration must be 0 < seconds <= 30")
    if not math.isfinite(period) or period <= 0:
        raise ValueError("period must be positive")
    if len({i.name for i in items}) != len(items):
        raise ValueError("Capture channel names must be unique")
    if any(i.size != 4 or i.address % 4 for i in items):
        raise ValueError(
            "Exact aligned 32-bit MMIO access required by current transport"
        )
    blocks = build_read_blocks(items, max_gap=0)
    if not 1 <= len(blocks) <= 15:
        raise ValueError("Capture supports 1..15 register regions")
    decoder = compile_frame_decoder(items, blocks)
    session = DumpMemoryStreamSession(
        device._bridge, [(b.address, b.size) for b in blocks], period
    )
    rows = []
    invalid = 0
    try:
        session.start()
        begin = time.monotonic()
        while time.monotonic() - begin < duration:
            for frame in session.read_frames(max_bytes=1024 * 1024):
                values = decoder.decode(frame)
                if frame.get("flags") or values is None:
                    invalid += 1
                    continue
                if len(rows) >= 100000:
                    raise ValueError(
                        "Capture result limit reached; reduce duration or rate"
                    )
                rows.append(
                    {"timestamp_us": frame["timestamp_us"], "values": list(values)}
                )
            time.sleep(0.001)
    finally:
        session.stop()
    if not rows:
        raise TimeoutError(
            f"No valid peripheral samples received ({invalid} invalid samples)"
        )
    return {
        "channels": list(decoder.channel_names),
        "samples": rows,
        "invalid_samples": invalid,
        "stats": session.stats,
    }
