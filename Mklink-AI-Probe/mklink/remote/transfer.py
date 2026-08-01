"""Atomic, quota-bound upload sessions for the direct Site Agent."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_NAME_RE = re.compile(r"^[^/\\\x00-\x1f]{1,255}$")
_MANAGED_PART_RE = re.compile(r"^\.[0-9a-f]{32}\.part$")
_WINDOWS_REPARSE_POINT = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x00000400,
)


class TransferError(Exception):
    """A safe public transfer-domain error."""


class TransferLimitError(TransferError):
    pass


class TransferStateError(TransferError):
    pass


class TransferIntegrityError(TransferError):
    pass


@dataclass(frozen=True)
class TransferLimits:
    max_file_bytes: int = 256 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_chunk_bytes: int = 256 * 1024
    max_active_sessions: int = 16
    idle_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        values = (
            self.max_file_bytes,
            self.max_total_bytes,
            self.max_chunk_bytes,
            self.max_active_sessions,
            self.idle_timeout_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError("all transfer limits must be positive")
        if self.max_chunk_bytes > self.max_file_bytes:
            raise ValueError("chunk limit cannot exceed file limit")
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError("file limit cannot exceed total quota")


@dataclass(frozen=True)
class RemoteFile:
    """Opaque server-side file reference returned after atomic finalization."""

    file_id: str
    name: str
    size: int
    sha256: str

    @property
    def reference(self) -> str:
        return f"remote-file:{self.file_id}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "reference": self.reference,
            "name": self.name,
            "size": self.size,
            "sha256": self.sha256,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "RemoteFile":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TransferStateError("Invalid remote file reference")
        file_id = value.get("file_id", value.get("id"))
        if not isinstance(file_id, str):
            reference = value.get("reference")
            if isinstance(reference, str) and reference.startswith("remote-file:"):
                file_id = reference.removeprefix("remote-file:")
        name = value.get("name", value.get("filename"))
        sha256 = value.get("sha256")
        size = value.get("size")
        if (
            not isinstance(file_id, str)
            or not file_id
            or not isinstance(name, str)
            or not isinstance(sha256, str)
            or isinstance(size, bool)
            or not isinstance(size, int)
        ):
            raise TransferStateError("Invalid remote file reference")
        return cls(file_id=file_id, name=name, size=size, sha256=sha256)


@dataclass
class _UploadSession:
    session_id: str
    name: str
    expected_size: int
    part_path: Path
    created_at: float
    updated_at: float
    offset: int = 0
    next_sequence: int = 0


@dataclass(frozen=True)
class _DirectoryIdentity:
    resolved: Path
    device: int
    inode: int


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & _WINDOWS_REPARSE_POINT
    )


def _is_real_entry(
    metadata: os.stat_result,
    *,
    directory: bool,
) -> bool:
    expected_type = (
        stat.S_ISDIR(metadata.st_mode)
        if directory
        else stat.S_ISREG(metadata.st_mode)
    )
    return (
        expected_type
        and not stat.S_ISLNK(metadata.st_mode)
        and not _is_reparse_point(metadata)
    )


def _windows_current_sid() -> str:
    """Return the current process-token user SID without exposing an identity."""

    import ctypes
    from ctypes import wintypes

    token_query = 0x0008
    token_user_class = 1

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [
            ("Sid", ctypes.c_void_p),
            ("Attributes", wintypes.DWORD),
        ]

    class TokenUser(ctypes.Structure):
        _fields_ = [("User", SidAndAttributes)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_uint,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        token_query,
        ctypes.byref(token),
    ):
        raise PermissionError("Unable to enforce owner-only permissions")
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token,
            token_user_class,
            None,
            0,
            ctypes.byref(required),
        )
        if required.value == 0:
            raise PermissionError("Unable to enforce owner-only permissions")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            token_user_class,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise PermissionError("Unable to enforce owner-only permissions")
        token_user = ctypes.cast(
            buffer,
            ctypes.POINTER(TokenUser),
        ).contents
        sid_text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            token_user.User.Sid,
            ctypes.byref(sid_text),
        ):
            raise PermissionError("Unable to enforce owner-only permissions")
        try:
            if not sid_text.value:
                raise PermissionError("Unable to enforce owner-only permissions")
            return sid_text.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)


def _windows_sid_text(sid: int) -> str:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertSidToStringSidW.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    text = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(
        ctypes.c_void_p(sid),
        ctypes.byref(text),
    ):
        raise PermissionError("Unable to verify owner-only permissions")
    try:
        if not text.value:
            raise PermissionError("Unable to verify owner-only permissions")
        return text.value
    finally:
        kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _set_windows_owner_only_acl(path: Path, *, directory: bool) -> None:
    import ctypes
    from ctypes import wintypes

    owner_security_information = 0x00000001
    dacl_security_information = 0x00000004
    protected_dacl_security_information = 0x80000000
    sddl_revision_1 = 1
    sid = _windows_current_sid()
    inheritance = "OICI" if directory else ""
    # Setting only the DACL is insufficient when the path was created under
    # an inherited/elevated owner (for example an SSH-launched process whose
    # profile directory is owned by the local Administrators group).  The
    # public contract requires the current identity to be both the owner and
    # the sole allowed principal, so apply both parts atomically.
    sddl = f"O:{sid}D:P(A;{inheritance};FA;;;{sid})"

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    advapi32.SetFileSecurityW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    advapi32.SetFileSecurityW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        sddl_revision_1,
        ctypes.byref(descriptor),
        None,
    ):
        raise PermissionError("Unable to enforce owner-only permissions")
    try:
        information = (
            owner_security_information
            | dacl_security_information
            | protected_dacl_security_information
        )
        if not advapi32.SetFileSecurityW(
            str(path),
            information,
            descriptor,
        ):
            raise PermissionError("Unable to enforce owner-only permissions")
    finally:
        kernel32.LocalFree(descriptor)


def _has_windows_owner_only_acl(
    path: Path,
    *,
    directory: bool,
) -> bool:
    import ctypes
    from ctypes import wintypes

    se_file_object = 1
    owner_security_information = 0x00000001
    dacl_security_information = 0x00000004
    acl_size_information = 2
    access_allowed_ace_type = 0
    inheritable_directory_flags = 0x03
    file_all_access = 0x001F01FF

    class AclSizeInformation(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    class AceHeader(ctypes.Structure):
        _fields_ = [
            ("AceType", ctypes.c_ubyte),
            ("AceFlags", ctypes.c_ubyte),
            ("AceSize", wintypes.WORD),
        ]

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = [
            ("Header", AceHeader),
            ("Mask", wintypes.DWORD),
            ("SidStart", wintypes.DWORD),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAclInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    )
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetAce.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path),
        se_file_object,
        owner_security_information | dacl_security_information,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if status != 0:
        raise PermissionError("Unable to verify owner-only permissions")
    try:
        if not owner.value or not dacl.value:
            return False
        current_sid = _windows_current_sid()
        if _windows_sid_text(owner.value) != current_sid:
            return False
        acl_info = AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(acl_info),
            ctypes.sizeof(acl_info),
            acl_size_information,
        ):
            raise PermissionError("Unable to verify owner-only permissions")
        if acl_info.AceCount != 1:
            return False
        ace_pointer = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
            raise PermissionError("Unable to verify owner-only permissions")
        ace = ctypes.cast(
            ace_pointer,
            ctypes.POINTER(AccessAllowedAce),
        ).contents
        if ace.Header.AceType != access_allowed_ace_type:
            return False
        if directory and (
            ace.Header.AceFlags & inheritable_directory_flags
        ) != inheritable_directory_flags:
            return False
        if not directory and ace.Header.AceFlags != 0:
            return False
        ace_sid = (
            ace_pointer.value
            + AccessAllowedAce.SidStart.offset
        )
        if _windows_sid_text(ace_sid) != current_sid:
            return False
        return (ace.Mask & file_all_access) == file_all_access
    finally:
        kernel32.LocalFree(descriptor)


def has_owner_only_permissions(
    path: Path,
    *,
    directory: bool = False,
) -> bool:
    """Verify the public owner-only filesystem contract."""

    target = Path(path)
    metadata = target.lstat()
    if not _is_real_entry(metadata, directory=directory):
        return False
    if os.name == "nt":
        return _has_windows_owner_only_acl(
            target,
            directory=directory,
        )
    expected = 0o700 if directory else 0o600
    return stat.S_IMODE(metadata.st_mode) == expected


def enforce_owner_only_permissions(
    path: Path,
    *,
    directory: bool = False,
) -> None:
    """Apply and verify owner-only access, failing closed on every platform."""

    target = Path(path)
    try:
        metadata = target.lstat()
    except OSError:
        raise PermissionError("Unable to enforce owner-only permissions") from None
    if not _is_real_entry(metadata, directory=directory):
        raise PermissionError("Unable to enforce owner-only permissions")
    if os.name == "nt":
        _set_windows_owner_only_acl(target, directory=directory)
    else:
        os.chmod(
            target,
            0o700 if directory else 0o600,
            follow_symlinks=False,
        )
    if not has_owner_only_permissions(target, directory=directory):
        raise PermissionError("Unable to enforce owner-only permissions")


def _restrict(path: Path, *, directory: bool = False) -> None:
    enforce_owner_only_permissions(path, directory=directory)


def _validate_filename(filename: str) -> str:
    if (
        not isinstance(filename, str)
        or filename in {"", ".", ".."}
        or Path(filename).name != filename
        or not _SAFE_NAME_RE.fullmatch(filename)
    ):
        raise TransferStateError("filename must be a safe basename")
    return filename


def _validate_session_id(session_id: str) -> str:
    if (
        not isinstance(session_id, str)
        or not 20 <= len(session_id) <= 128
        or not all(char.isalnum() or char in "-_" for char in session_id)
    ):
        raise TransferStateError("Unknown upload session")
    return session_id


class UploadManager:
    """Own opaque upload sessions and publish files only after integrity checks."""

    def __init__(
        self,
        root: Path,
        *,
        limits: TransferLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.root = Path(
            os.path.abspath(os.fspath(Path(root).expanduser()))
        )
        self.limits = limits or TransferLimits()
        self._clock = clock
        self._pending_dir = self.root / "pending"
        self._files_dir = self.root / "files"
        self._sessions: dict[str, _UploadSession] = {}
        self._lock = threading.RLock()
        self._directory_identities: tuple[
            _DirectoryIdentity,
            _DirectoryIdentity,
            _DirectoryIdentity,
        ]
        self._initialize_directories()
        # Reconcile process-lifetime storage immediately. Legacy pending files
        # are retained (another process may still own one) and accounted by
        # every quota decision rather than being silently ignored.
        with self._lock:
            self._storage_usage_locked()

    def open(
        self,
        filename: str,
        size: int,
        *,
        resume: bool = False,
        offset: int | None = None,
        destination: str | Path | None = None,
    ) -> dict[str, Any]:
        """Create a fresh opaque session; resumption and destinations are invalid."""

        if resume or offset not in (None, 0):
            raise TransferStateError("Upload resume is not supported")
        if destination is not None:
            raise TransferStateError("Client-selected upload destinations are not supported")
        filename = _validate_filename(filename)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise TransferStateError("upload size must be a non-negative integer")
        if size > self.limits.max_file_bytes:
            raise TransferLimitError("upload exceeds the per-file limit")

        with self._lock:
            self._validate_controlled_directories_locked()
            self.cleanup_idle()
            if len(self._sessions) >= self.limits.max_active_sessions:
                raise TransferLimitError("too many active upload sessions")
            published, retained_pending, reserved = self._storage_usage_locked()
            if (
                published
                + retained_pending
                + reserved
                + size
                > self.limits.max_total_bytes
            ):
                raise TransferLimitError("upload storage quota exceeded")

            now = self._clock()
            while True:
                session_id = secrets.token_urlsafe(24)
                part_path = self._pending_dir / f".{secrets.token_hex(16)}.part"
                try:
                    descriptor = os.open(
                        str(part_path),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        stat.S_IRUSR | stat.S_IWUSR,
                    )
                except FileExistsError:
                    continue
                os.close(descriptor)
                try:
                    self._validate_controlled_directories_locked()
                    if not self._is_managed_pending_file_locked(part_path):
                        raise TransferStateError("Unable to store upload data")
                    _restrict(part_path)
                except Exception:
                    try:
                        self._unlink_managed_pending_locked(part_path)
                    except TransferStateError:
                        pass
                    raise
                break
            self._sessions[session_id] = _UploadSession(
                session_id=session_id,
                name=filename,
                expected_size=size,
                part_path=part_path,
                created_at=now,
                updated_at=now,
            )
            return {
                "session_id": session_id,
                "chunk_limit": self.limits.max_chunk_bytes,
                "expires_at": now + self.limits.idle_timeout_seconds,
            }

    def chunk(
        self,
        session_id: str,
        offset: int,
        sequence: int,
        data: bytes,
        *,
        resume: bool = False,
    ) -> dict[str, int]:
        if resume:
            raise TransferStateError("Upload resume is not supported")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TransferStateError("upload chunk data must be bytes")
        payload = bytes(data)
        if not payload:
            raise TransferStateError("upload chunks cannot be empty")
        if len(payload) > self.limits.max_chunk_bytes:
            raise TransferLimitError("upload chunk exceeds the chunk limit")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise TransferStateError("invalid upload offset")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise TransferStateError("invalid upload sequence")

        with self._lock:
            self._validate_controlled_directories_locked()
            session = self._session_locked(session_id)
            if offset != session.offset or sequence != session.next_sequence:
                raise TransferStateError("upload chunks must be contiguous and in sequence")
            if session.offset + len(payload) > session.expected_size:
                raise TransferLimitError("upload data exceeds the declared size")
            if not self._is_managed_pending_file_locked(session.part_path):
                self._abort_locked(session.session_id)
                raise TransferStateError("Unable to store upload data")
            try:
                self._validate_controlled_directories_locked()
                with session.part_path.open("ab") as output:
                    output.write(payload)
                    output.flush()
            except Exception as exc:
                self._abort_locked(session.session_id)
                raise TransferStateError("Unable to store upload data") from exc
            session.offset += len(payload)
            session.next_sequence += 1
            session.updated_at = self._clock()
            return {
                "written": len(payload),
                "offset": session.offset,
                "next_sequence": session.next_sequence,
            }

    def finalize(self, session_id: str, size: int, sha256: str) -> RemoteFile:
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or not _SHA256_RE.fullmatch(sha256)
        ):
            raise TransferIntegrityError("Invalid final size or SHA-256")

        with self._lock:
            self._validate_controlled_directories_locked()
            session = self._session_locked(session_id)
            if size != session.expected_size or size != session.offset:
                self._abort_locked(session.session_id)
                raise TransferIntegrityError("Upload size mismatch")
            if not self._is_managed_pending_file_locked(session.part_path):
                self._abort_locked(session.session_id)
                raise TransferStateError("Unable to verify upload data")
            digest = hashlib.sha256()
            try:
                self._validate_controlled_directories_locked()
                with session.part_path.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
            except OSError as exc:
                self._abort_locked(session.session_id)
                raise TransferStateError("Unable to verify upload data") from exc
            actual_sha256 = digest.hexdigest()
            if not secrets.compare_digest(actual_sha256, sha256.lower()):
                self._abort_locked(session.session_id)
                raise TransferIntegrityError("Upload SHA-256 mismatch")

            while True:
                file_id = secrets.token_urlsafe(24)
                final_path = self._files_dir / f"{file_id}-{session.name}"
                try:
                    final_path.lstat()
                except FileNotFoundError:
                    break
                except OSError as exc:
                    raise TransferStateError(
                        "Unable to finalize upload"
                    ) from exc
            published = False
            try:
                self._validate_controlled_directories_locked()
                if not self._is_managed_pending_file_locked(session.part_path):
                    raise TransferStateError("Unable to finalize upload")
                os.replace(session.part_path, final_path)
                published = True
                self._validate_controlled_directories_locked()
                if not self._is_managed_final_file_locked(final_path):
                    raise TransferStateError("Unable to finalize upload")
                _restrict(final_path)
            except (OSError, TransferStateError) as exc:
                if published:
                    try:
                        self._unlink_managed_final_locked(final_path)
                    except (OSError, TransferStateError):
                        pass
                try:
                    self._abort_locked(session.session_id)
                except TransferStateError:
                    pass
                raise TransferStateError("Unable to finalize upload") from exc
            del self._sessions[session.session_id]
            return RemoteFile(
                file_id=file_id,
                name=session.name,
                size=size,
                sha256=actual_sha256,
            )

    def abort(self, session_id: str) -> bool:
        with self._lock:
            self._validate_controlled_directories_locked()
            return self._abort_locked(_validate_session_id(session_id))

    def cleanup_idle(self, *, now: float | None = None) -> int:
        with self._lock:
            self._validate_controlled_directories_locked()
            cutoff = (self._clock() if now is None else float(now)) - self.limits.idle_timeout_seconds
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if session.updated_at <= cutoff
            ]
            for session_id in expired:
                self._abort_locked(session_id)
            return len(expired)

    def close(self) -> None:
        """Remove all incomplete sessions without touching published files."""

        with self._lock:
            self._validate_controlled_directories_locked()
            for session_id in list(self._sessions):
                self._abort_locked(session_id)

    def resolve(self, remote_file: RemoteFile | str) -> Path:
        """Resolve an opaque reference internally; arbitrary paths are impossible."""

        file_id = (
            remote_file.file_id
            if isinstance(remote_file, RemoteFile)
            else str(remote_file).removeprefix("remote-file:")
        )
        if not file_id or not all(char.isalnum() or char in "-_" for char in file_id):
            raise TransferStateError("Invalid remote file reference")
        with self._lock:
            self._validate_controlled_directories_locked()
            matches = list(self._files_dir.glob(f"{file_id}-*"))
            self._validate_controlled_directories_locked()
            if (
                len(matches) != 1
                or not self._is_managed_final_file_locked(matches[0])
            ):
                raise TransferStateError("Unknown remote file reference")
            return matches[0]

    def _storage_usage_locked(self) -> tuple[int, int, int]:
        """Return published, retained-pending, and active-reserved bytes.

        Current-session part files are excluded from the second value because
        their complete declared sizes are included in the third. If an active
        part is unexpectedly larger than its declaration, its actual size wins
        so filesystem tampering cannot create an accounting gap. Every other
        regular file directly inside the controlled pending directory is
        retained and counted conservatively.
        """

        self._validate_controlled_directories_locked()
        active_parts = {
            session.part_path: session.expected_size
            for session in self._sessions.values()
            if self._is_managed_pending_path(session.part_path)
        }
        try:
            published = self._regular_file_bytes_locked(self._files_dir)
            retained_pending = self._regular_file_bytes_locked(
                self._pending_dir,
                excluded=set(active_parts),
            )
            reserved = sum(
                session.expected_size for session in self._sessions.values()
            )
            for path, expected_size in active_parts.items():
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                if _is_real_entry(metadata, directory=False):
                    reserved += max(0, metadata.st_size - expected_size)
        except OSError:
            raise TransferStateError("Unable to inspect upload storage") from None
        self._validate_controlled_directories_locked()
        return published, retained_pending, reserved

    def _regular_file_bytes_locked(
        self,
        directory: Path,
        *,
        excluded: set[Path] | None = None,
    ) -> int:
        self._validate_controlled_directories_locked()
        excluded = excluded or set()
        total = 0
        for path in directory.iterdir():
            if path in excluded:
                continue
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
            if _is_real_entry(metadata, directory=False):
                total += metadata.st_size
        self._validate_controlled_directories_locked()
        return total

    def _is_managed_pending_path(self, path: Path) -> bool:
        candidate = Path(path)
        return (
            candidate.parent == self._pending_dir
            and _MANAGED_PART_RE.fullmatch(candidate.name) is not None
        )

    def _is_managed_pending_file_locked(self, path: Path) -> bool:
        if not self._is_managed_pending_path(path):
            return False
        try:
            metadata = Path(path).lstat()
        except OSError:
            return False
        return _is_real_entry(metadata, directory=False)

    def _unlink_managed_pending_locked(self, path: Path) -> bool:
        self._validate_controlled_directories_locked()
        if not self._is_managed_pending_file_locked(path):
            return False
        try:
            Path(path).unlink()
        except OSError:
            return False
        return True

    def _is_managed_final_file_locked(self, path: Path) -> bool:
        candidate = Path(path)
        if candidate.parent != self._files_dir:
            return False
        try:
            metadata = candidate.lstat()
        except OSError:
            return False
        return _is_real_entry(metadata, directory=False)

    def _unlink_managed_final_locked(self, path: Path) -> bool:
        self._validate_controlled_directories_locked()
        if not self._is_managed_final_file_locked(path):
            return False
        try:
            Path(path).unlink()
        except OSError:
            return False
        return True

    def _initialize_directories(self) -> None:
        try:
            self.root.lstat()
        except FileNotFoundError:
            self.root.mkdir(parents=True)
        except OSError:
            raise TransferStateError("Unable to initialize upload storage") from None
        self._capture_directory_identity(self.root)

        missing: list[Path] = []
        for directory in (self._pending_dir, self._files_dir):
            try:
                metadata = directory.lstat()
            except FileNotFoundError:
                missing.append(directory)
                continue
            except OSError:
                raise TransferStateError(
                    "Unable to initialize upload storage"
                ) from None
            if not _is_real_entry(metadata, directory=True):
                raise TransferStateError("Unable to initialize upload storage")

        for directory in missing:
            try:
                directory.mkdir()
            except FileExistsError:
                pass
            except OSError:
                raise TransferStateError(
                    "Unable to initialize upload storage"
                ) from None

        self._directory_identities = (
            self._capture_controlled_directories_locked()
        )
        for directory in (self.root, self._pending_dir, self._files_dir):
            self._validate_controlled_directories_locked()
            _restrict(directory, directory=True)
            self._validate_controlled_directories_locked()

    @staticmethod
    def _capture_directory_identity(path: Path) -> _DirectoryIdentity:
        try:
            metadata = path.lstat()
            if not _is_real_entry(metadata, directory=True):
                raise TransferStateError("Upload storage is unavailable")
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise TransferStateError("Upload storage is unavailable") from None
        return _DirectoryIdentity(
            resolved=resolved,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )

    def _capture_controlled_directories_locked(
        self,
    ) -> tuple[
        _DirectoryIdentity,
        _DirectoryIdentity,
        _DirectoryIdentity,
    ]:
        if (
            self._pending_dir.parent != self.root
            or self._files_dir.parent != self.root
        ):
            raise TransferStateError("Upload storage is unavailable")
        root_identity = self._capture_directory_identity(self.root)
        pending_identity = self._capture_directory_identity(
            self._pending_dir
        )
        files_identity = self._capture_directory_identity(self._files_dir)
        if (
            pending_identity.resolved.parent != root_identity.resolved
            or files_identity.resolved.parent != root_identity.resolved
        ):
            raise TransferStateError("Upload storage is unavailable")
        return root_identity, pending_identity, files_identity

    def _validate_controlled_directories_locked(self) -> None:
        current = self._capture_controlled_directories_locked()
        if current != self._directory_identities:
            raise TransferStateError("Upload storage is unavailable")

    def _session_locked(self, session_id: str) -> _UploadSession:
        session_id = _validate_session_id(session_id)
        session = self._sessions.get(session_id)
        if session is None:
            raise TransferStateError("Unknown upload session")
        if self._clock() - session.updated_at >= self.limits.idle_timeout_seconds:
            self._abort_locked(session_id)
            raise TransferStateError("Upload session expired")
        return session

    def _abort_locked(self, session_id: str) -> bool:
        self._validate_controlled_directories_locked()
        session = self._sessions.get(session_id)
        if session is None:
            return False
        self._unlink_managed_pending_locked(session.part_path)
        del self._sessions[session_id]
        return True


# Name aligned with the protocol concern while retaining the explicit upload name.
TransferManager = UploadManager


__all__ = [
    "RemoteFile",
    "TransferError",
    "TransferIntegrityError",
    "TransferLimitError",
    "TransferLimits",
    "TransferManager",
    "TransferStateError",
    "UploadManager",
    "enforce_owner_only_permissions",
    "has_owner_only_permissions",
]
