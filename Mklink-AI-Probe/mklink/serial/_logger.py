"""串口数据文件日志记录器。"""

from __future__ import annotations

import csv
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import IO
from ._frame import json_fields


def _is_printable_ascii(data: bytes) -> bool:
    return all(b in range(0x20, 0x7F) or b in (0x0A, 0x0D, 0x09) for b in data)


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


class FileLogger:
    def __init__(self, path: str, format: str = "txt", max_size: int = 0) -> None:
        self._path = Path(path)
        if format not in ('txt', 'csv'):
            raise ValueError('Log format must be txt or csv')
        self._format = format
        self._max_size = max_size
        self._file: IO[str] | None = None
        self._lock = threading.Lock()
        self._csv_header_written = False
        self._rotation_index = 0

    def start(self, *, exclusive: bool = False) -> None:
        with self._lock:
            if self._file is not None:
                raise RuntimeError('Log is already open')
            self._file = open(self._path, "x" if exclusive else "w", encoding="utf-8", newline="")
            if self._format == "csv":
                self._csv_header_written = False

    def log(self, direction: str, port: str, data: bytes, decoded: dict | None = None,
            *, timestamp: float | None = None, frames: list[dict] | None = None) -> None:
        with self._lock:
            if self._file is None:
                raise RuntimeError('Log is not open')

            now = datetime.now() if timestamp is None else datetime.fromtimestamp(timestamp)
            annotations = frames if frames is not None else ([{'fields': json_fields(decoded)}] if decoded else [])

            if self._format == "txt":
                self._write_txt(now, direction, port, data, annotations)
            else:
                self._write_csv(now, direction, port, data, annotations)

            self._file.flush()
            self._maybe_rotate()

    def close(self) -> None:
        with self._lock:
            stream, self._file = self._file, None
            if stream is not None:
                try:
                    stream.flush()
                finally:
                    stream.close()

    def __enter__(self) -> FileLogger:
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            self.close()
        except OSError as error:
            if exc_type is None:
                raise
            print(f'[WARN] Log close failed: {error}', file=sys.stderr)

    def _write_txt(
        self,
        now: datetime,
        direction: str,
        port: str,
        data: bytes,
        frames: list[dict],
    ) -> None:
        ts = _format_timestamp(now)
        text = repr(data.decode('ascii')) if _is_printable_ascii(data) else ''
        line = f"[{ts}] {direction} {port}: {data.hex(' ').upper()} {text}\n"

        self._file.write(line)  # type: ignore[union-attr]

        for frame in frames:
            self._file.write('  decoded: ' + json.dumps(frame, ensure_ascii=False, allow_nan=False) + '\n')

    def _write_csv(self, now: datetime, direction: str, port: str,
                   data: bytes, frames: list[dict]) -> None:
        writer = csv.writer(self._file, lineterminator='\r\n')
        if not self._csv_header_written:
            writer.writerow(['timestamp', 'direction', 'port', 'raw_hex', 'ascii', 'decoded_json'])
            self._csv_header_written = True
        writer.writerow([_format_timestamp(now), direction, port, data.hex().upper(),
                         data.decode('ascii') if _is_printable_ascii(data) else '',
                         json.dumps(frames, ensure_ascii=False, allow_nan=False) if frames else ''])

    def _maybe_rotate(self) -> None:
        if self._max_size <= 0 or self._file is None:
            return

        self._file.flush()
        try:
            size = os.fstat(self._file.fileno()).st_size
        except OSError:
            size = self._path.stat().st_size

        if size < self._max_size:
            return

        stream, self._file = self._file, None
        stream.close()

        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        while True:
            index = self._rotation_index
            self._rotation_index += 1
            discriminator = f'_{index}' if index else ''
            rotated_path = self._path.with_name(
                f'{self._path.stem}_{stamp}{discriminator}{self._path.suffix}')
            try:
                # Reserve exclusively: replace must never overwrite an older log.
                with rotated_path.open('x', encoding='utf-8'):
                    pass
                break
            except FileExistsError:
                continue
        try:
            self._path.replace(rotated_path)
        except OSError:
            rotated_path.unlink(missing_ok=True)
            raise

        # A failed rotation leaves the logger closed and the error visible.
        # Do not truncate a file created at the base path by another writer.
        self._file = open(self._path, "x", encoding="utf-8", newline="")
        self._csv_header_written = False
