"""Stable filesystem locations for CMSIS-Pack catalog data."""

from dataclasses import dataclass, field
import os
from pathlib import Path


def _default_root() -> Path:
    configured = os.environ.get("MKLINK_PYOCD_HOME")
    if configured:
        return Path(configured)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "MKLink" / "pyocd"

    return Path.home() / "AppData" / "Local" / "MKLink" / "pyocd"


@dataclass(frozen=True)
class PackPaths:
    """Paths used by the local CMSIS-Pack cache."""

    root: Path = field(default_factory=_default_root)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    @property
    def index_file(self) -> Path:
        return self.index_dir / "index.json"

    @property
    def aliases_file(self) -> Path:
        return self.index_dir / "aliases.json"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def staging_dir(self) -> Path:
        return self.root / "staging"

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"
