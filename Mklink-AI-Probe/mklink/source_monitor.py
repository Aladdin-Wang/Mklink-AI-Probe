"""Low-rate content change detection, independent of probe I/O and timestamps."""
from pathlib import Path

from mklink.file_content import source_fingerprint


class SourceMonitor:
    def __init__(self):
        self.device = None
        self.previous = {}
        self.pending = {}

    def acknowledge(self, device, snapshot):
        """Only retire changes actually handled for this device and content."""
        if device is not self.device:
            return
        for path, fingerprint in snapshot.items():
            if path in self.pending and self.pending[path] == fingerprint:
                self.pending.pop(path)

    def changed(self, device, project: dict) -> list[str]:
        if device is not self.device:
            self.device, self.previous = device, {}
            self.pending = {}
        catalog = getattr(device, "symbol_catalog", None)
        axf = (getattr(device, "_axf", None) or project.get("axf_path")
               or project.get("elf_path") or project.get("out_path"))
        paths = [path for path in (axf, project.get("map_path")) if path]
        current = {}
        changed = []
        for path in dict.fromkeys(paths):
            try:
                current[path] = source_fingerprint(path)
            except OSError:
                current[path] = None
            previous = self.previous.get(path, current[path])
            if path not in self.previous and catalog is not None and Path(path) == Path(catalog.axf_path):
                previous = catalog.fingerprint.to_dict()
            if previous != current[path]:
                changed.append(path)
                self.pending[path] = current[path]
        self.previous = current
        self.pending = {path: value for path, value in self.pending.items() if path in current}
        return changed
