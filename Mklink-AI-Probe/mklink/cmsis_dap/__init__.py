"""Public, backend-independent contracts for online CMSIS-DAP flashing."""

from .errors import FLASH_ERROR_TITLES, FlashError, FlashErrorCode
from .models import (
    ALLOWED_TRANSITIONS,
    ImageInspection,
    ImageSegment,
    JobEvent,
    JobRequest,
    JobSnapshot,
    JobState,
    MemoryRegion,
    PackRecord,
    ProbeRecord,
    TargetRecord,
    assert_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "FLASH_ERROR_TITLES",
    "FlashError",
    "FlashErrorCode",
    "ImageInspection",
    "ImageSegment",
    "JobEvent",
    "JobRequest",
    "JobSnapshot",
    "JobState",
    "MemoryRegion",
    "PackRecord",
    "ProbeRecord",
    "TargetRecord",
    "assert_transition",
]
