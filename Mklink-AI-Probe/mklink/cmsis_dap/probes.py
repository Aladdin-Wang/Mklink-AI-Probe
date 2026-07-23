"""MKLink CMSIS-DAP probe filtering without hardware enumeration."""
from __future__ import annotations

from collections.abc import Iterable
import os
from typing import Any

from .models import ProbeRecord


_IDENTITY_TOKENS = ("mklink", "microlink", "microkeen")


def _parse_usb_id(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        return int(value, 16)


def _usb_ids_from_environment() -> set[tuple[int, int]]:
    allowed: set[tuple[int, int]] = set()
    for item in os.environ.get("MKLINK_CMSIS_DAP_USB_IDS", "").split(","):
        try:
            vid, pid = (part.strip() for part in item.split(":", 1))
            allowed.add((_parse_usb_id(vid), _parse_usb_id(pid)))
        except (TypeError, ValueError):
            continue
    return allowed


def _probe_usb_id(probe: Any) -> tuple[int | None, int | None]:
    vid = getattr(probe, "vid", getattr(probe, "vendor_id", None))
    pid = getattr(probe, "pid", getattr(probe, "product_id", None))
    return vid, pid


def filter_mklink_probes(
    probes: Iterable[Any],
    allowed_usb_ids: set[tuple[int, int]] | None = None,
) -> list[ProbeRecord]:
    """Return only probes whose descriptive identity identifies MKLink."""
    allowed_ids = (
        set(allowed_usb_ids)
        if allowed_usb_ids is not None
        else _usb_ids_from_environment()
    )
    records_by_id: dict[str, ProbeRecord] = {}
    for probe in probes:
        unique_id = str(getattr(probe, "unique_id", "") or "").strip()
        vid, pid = _probe_usb_id(probe)
        identity = " ".join(
            str(getattr(probe, field, "") or "")
            for field in ("vendor_name", "product_name", "description")
        ).casefold()
        matches_usb_id = vid is not None and pid is not None and (vid, pid) in allowed_ids
        matches_identity = any(token in identity for token in _IDENTITY_TOKENS)
        if unique_id and (matches_usb_id or matches_identity) and unique_id not in records_by_id:
            records_by_id[unique_id] = ProbeRecord(
                unique_id=unique_id,
                vendor_name=str(getattr(probe, "vendor_name", "") or ""),
                product_name=str(getattr(probe, "product_name", "") or ""),
                description=str(getattr(probe, "description", "") or ""),
                vid=vid,
                pid=pid,
                serial_number=getattr(probe, "serial_number", None),
            )
    return sorted(
        records_by_id.values(),
        key=lambda record: (record.product_name.casefold(), record.unique_id),
    )
