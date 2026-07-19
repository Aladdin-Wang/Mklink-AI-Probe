"""Cancellable, on-demand CMSIS-Pack installation."""

import json
import os
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Callable, Dict, Mapping, Optional, Tuple
import uuid

from .errors import FlashError, FlashErrorCode
from .pack_lock import PackRootLock
from .process_guard import (
    attach_and_release_guarded_process,
    guarded_process_command,
    guarded_process_creationflags,
)
from .paths import PackPaths


EventCallback = Callable[[Dict[str, object]], None]


def _resolved_child(path: Path, parent: Path, description: str) -> Path:
    resolved_parent = parent.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_parent)
    except ValueError:
        raise FlashError(
            FlashErrorCode.PACK_INTEGRITY_ERROR,
            "{} is outside the managed directory".format(description),
        )
    if resolved_path == resolved_parent:
        raise FlashError(
            FlashErrorCode.PACK_INTEGRITY_ERROR,
            "{} must not be the managed directory itself".format(description),
        )
    return resolved_path


def _identity_segment(value: object, description: str) -> str:
    if not isinstance(value, str) or not value or value in (".", ".."):
        raise ValueError("{} is not a valid pack identity segment".format(description))
    if "/" in value or "\\" in value or Path(value).drive or Path(value).is_absolute():
        raise ValueError("{} must not contain a path".format(description))
    return value


def _normalize_pack_identity(
    vendor: object,
    pack: object,
    version: object,
) -> Tuple[str, str, str, str]:
    vendor_text = _identity_segment(vendor, "vendor")
    pack_text = _identity_segment(pack, "pack")
    prefix = vendor_text + "."
    pack_name = pack_text[len(prefix):] if pack_text.startswith(prefix) else pack_text
    pack_name = _identity_segment(pack_name, "pack")
    version_text = _identity_segment(version, "version")
    return vendor_text, pack_name, version_text, prefix + pack_name


def _canonical_pack_path(
    paths: PackPaths,
    vendor: object,
    pack: object,
    version: object,
) -> Path:
    vendor_text, pack_name, version_text, pack_id = _normalize_pack_identity(
        vendor, pack, version
    )
    resolved_data = _resolved_child(
        paths.data_dir, paths.root, "pack data directory"
    )
    candidate = (
        resolved_data
        / vendor_text
        / pack_name
        / version_text
        / "{}.{}.pack".format(pack_id, version_text)
    )
    return _resolved_child(candidate, resolved_data, "canonical pack path")


class SubprocessPackWorker:
    """Run the network-facing pack operations behind a JSON-lines boundary."""

    def __init__(self, paths: PackPaths) -> None:
        self._paths = paths
        self._lock = threading.Lock()
        self._recovery_lock = threading.Lock()
        self._process = None  # type: Optional[subprocess.Popen]
        self._process_guard = None
        self._cancel_requested = False
        self._active_staging_dir = None  # type: Optional[Path]
        self._committed_result = None  # type: Optional[Dict[str, object]]

    @property
    def active_staging_dir(self) -> Optional[Path]:
        with self._lock:
            return self._active_staging_dir

    @property
    def committed_result(self) -> Optional[Dict[str, object]]:
        with self._lock:
            return (
                dict(self._committed_result)
                if self._committed_result is not None
                else None
            )

    @staticmethod
    def _worker_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--internal-pack-worker"]
        return [sys.executable, "-m", "mklink.cmsis_dap.pack_worker"]

    def run(
        self,
        command: str,
        payload: Dict[str, object],
        on_event: EventCallback,
    ) -> Dict[str, object]:
        process_guard = None
        staging = (self._paths.staging_dir / uuid.uuid4().hex).resolve()
        if staging.parent != self._paths.staging_dir.resolve():
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "worker staging must be a direct child",
            )
        request = {
            "command": command,
            "payload": payload,
            "root": str(self._paths.root.resolve()),
            "staging_dir": str(staging),
        }
        with self._lock:
            if self._cancel_requested:
                self._cancel_requested = False
                self._active_staging_dir = None
                raise FlashError(FlashErrorCode.USER_ABORT, "pack operation cancelled")
            if self._process is not None:
                raise FlashError(FlashErrorCode.PROBE_BUSY, "pack worker is busy")
            self._active_staging_dir = staging
            try:
                process = subprocess.Popen(
                    guarded_process_command(self._worker_command()),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    creationflags=guarded_process_creationflags(),
                )
                process_guard = attach_and_release_guarded_process(process)
            except BaseException:
                self._active_staging_dir = None
                raise
            self._process = process
            self._process_guard = process_guard

        stderr_parts = []  # type: list
        stderr_thread = None  # type: Optional[threading.Thread]
        preserve_staging = False
        try:

            def drain_stderr() -> None:
                stderr_parts.append(process.stderr.read())

            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            process.stdin.close()
            result, worker_error = self._read_stdout(process.stdout, on_event)
            returncode = process.wait()
            stderr_thread.join(timeout=5)
            stderr = "".join(stderr_parts)
            self._recover_pending_transaction(preserve_committed=True)
            if self._committed_result is not None:
                preserve_staging = True
            if worker_error is not None:
                self._raise_worker_error(command, worker_error, stderr)
            return self._finish_result(command, returncode, result, stderr)
        except BaseException as error:
            self._close_process_guard(process, process_guard)
            self._stop_process(process)
            if stderr_thread is not None:
                stderr_thread.join(timeout=5)
            try:
                self._recover_pending_transaction(preserve_committed=True)
            except FlashError:
                preserve_staging = True
                raise
            if self._committed_result is not None:
                preserve_staging = True
                return self._finish_result(command, process.returncode or 1, None, str(error))
            if isinstance(error, OSError):
                with self._lock:
                    cancelled = self._cancel_requested
                    self._cancel_requested = False
                if cancelled:
                    raise FlashError(FlashErrorCode.USER_ABORT, "pack operation cancelled")
                raise FlashError(
                    FlashErrorCode.PACK_DOWNLOAD_FAIL,
                    "pack worker pipe failed: {}".format(error),
                )
            raise
        finally:
            self._close_process_guard(process, process_guard)
            if not preserve_staging:
                self._cleanup_active_staging()
            with self._lock:
                if self._process is process:
                    self._process = None
                    self._process_guard = None
                self._cancel_requested = False

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            process = self._process
            process_guard = self._process_guard
            self._process_guard = None
        if process_guard is not None:
            process_guard.close()
        if process is not None and process.poll() is None:
            self._stop_process(process)
        self._recover_pending_transaction(preserve_committed=True)
        if self._committed_result is None:
            self._cleanup_active_staging()

    def _recover_pending_transaction(self, preserve_committed: bool = False) -> None:
        from .pack_worker import WorkerFailure, recover_pending_transaction

        with self._recovery_lock:
            try:
                committed = recover_pending_transaction(
                    self._paths, preserve_committed=preserve_committed
                )
                if committed is not None:
                    with self._lock:
                        self._committed_result = committed
            except WorkerFailure as error:
                raise FlashError(error.code, error.message)
            except OSError as error:
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "pack transaction recovery failed: {}".format(error),
                )

    def acknowledge_commit(self, result: Mapping[str, object]) -> None:
        from .pack_worker import acknowledge_committed_transaction

        acknowledge_committed_transaction(self._paths, result)
        with self._lock:
            self._committed_result = None
            self._cancel_requested = False
        self._cleanup_active_staging()

    def rollback_commit(self, result: Mapping[str, object]) -> None:
        from .pack_worker import rollback_committed_transaction

        rollback_committed_transaction(self._paths, result)
        with self._lock:
            self._committed_result = None
            self._cancel_requested = False
        self._cleanup_active_staging()

    @staticmethod
    def _stop_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _close_process_guard(self, process: object, fallback: object = None) -> None:
        with self._lock:
            guard = None
            if self._process is process:
                guard = self._process_guard
                self._process_guard = None
        if guard is None:
            guard = fallback
        if guard is not None:
            guard.close()

    def _read_stdout(
        self,
        lines: object,
        on_event: EventCallback,
    ) -> Tuple[Optional[Dict[str, object]], Optional[Dict[str, object]]]:
        result = None  # type: Optional[Dict[str, object]]
        worker_error = None  # type: Optional[Dict[str, object]]
        for line in lines:
            message = SubprocessPackWorker._decode_message(line)
            message_type = message.get("type")
            if message_type == "event" and message.get("event") == "staging":
                self._capture_staging(message)
            elif message_type in ("progress", "log"):
                on_event(dict(message))
            elif message_type == "result":
                value = message.get("result")
                if not isinstance(value, Mapping):
                    raise FlashError(
                        FlashErrorCode.PACK_INTEGRITY_ERROR,
                        "pack worker result must be an object",
                    )
                result = dict(value)
            elif message_type == "error":
                worker_error = dict(message)
        return result, worker_error

    def _capture_staging(self, message: Mapping[str, object]) -> None:
        value = message.get("path")
        if not isinstance(value, str):
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack worker staging event has no path",
            )
        staging_root = self._paths.staging_dir.resolve()
        staging = _resolved_child(Path(value), staging_root, "worker staging")
        if staging.parent != staging_root:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack worker staging must be a direct child",
            )
        with self._lock:
            expected = self._active_staging_dir
        if expected is None or staging != expected:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack worker confirmed an unexpected staging directory",
            )

    def _cleanup_active_staging(self) -> None:
        with self._lock:
            staging = self._active_staging_dir
            self._active_staging_dir = None
        if staging is None:
            return
        try:
            verified = _resolved_child(
                staging,
                self._paths.staging_dir,
                "worker staging",
            )
        except FlashError:
            return
        if verified.parent == self._paths.staging_dir.resolve() and verified.exists():
            shutil.rmtree(str(verified))
        try:
            self._paths.staging_dir.rmdir()
        except OSError:
            pass

    @staticmethod
    def _decode_message(line: str) -> Dict[str, object]:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack worker emitted invalid JSON: {}".format(error),
            )
        if not isinstance(message, Mapping):
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack worker message must be an object",
            )
        return dict(message)

    def _finish_result(
        self,
        command: str,
        returncode: int,
        result: Optional[Dict[str, object]],
        stderr: str,
    ) -> Dict[str, object]:
        with self._lock:
            cancelled = self._cancel_requested
            if cancelled:
                self._cancel_requested = False
            committed = self._committed_result
        if committed is not None:
            if result is not None and result != committed:
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "worker result does not match committed transaction",
                )
            return dict(committed)
        if cancelled:
            raise FlashError(FlashErrorCode.USER_ABORT, "pack operation cancelled")
        if returncode != 0 or result is None:
            details = {"stderr": stderr.strip()} if stderr.strip() else None
            raise FlashError(
                FlashErrorCode.PACK_DOWNLOAD_FAIL,
                "pack worker failed with exit code {}".format(returncode),
                details,
            )
        if command == "update-index":
            target_count = result.get("target_count")
            if (
                result.get("status") != "updated"
                or type(target_count) is not int
                or target_count < 0
            ):
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "pack index worker result is invalid",
                )
            return result
        required = ("status", "pack_id", "version", "pack_path")
        missing = [key for key in required if not result.get(key)]
        if missing:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack worker result missing {}".format(", ".join(missing)),
            )
        return result

    @staticmethod
    def _raise_worker_error(
        command: str,
        message: Mapping[str, object],
        stderr: str,
    ) -> None:
        code_value = message.get("code")
        try:
            code = FlashErrorCode(str(code_value))
        except ValueError:
            code = (
                FlashErrorCode.PACK_INTEGRITY_ERROR
                if command == "import"
                else FlashErrorCode.PACK_DOWNLOAD_FAIL
            )
        details = {"stderr": stderr.strip()} if stderr.strip() else None
        raise FlashError(code, str(message.get("message") or "pack worker failed"), details)


class PackManager:
    """Coordinate pack worker commands and the installed-pack registry."""

    def __init__(
        self,
        root: Path,
        worker: Optional[object] = None,
        *,
        lock_timeout: float = 30.0,
    ) -> None:
        if not isinstance(lock_timeout, (int, float)) or lock_timeout <= 0:
            raise ValueError("lock_timeout must be positive")
        self.paths = PackPaths(Path(root))
        self._worker = worker if worker is not None else SubprocessPackWorker(self.paths)
        self._root_lock = PackRootLock(self.paths.root)
        self._lock_timeout = float(lock_timeout)
        self._cancel_event = threading.Event()
        self._active_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active = False
        self._cancel_requested = False
        self._phase = "idle"
        self._operation_token = 0

    def install(self, part_number: str, on_event: EventCallback) -> Dict[str, object]:
        if not isinstance(part_number, str) or not part_number.strip():
            raise ValueError("part number must be a non-empty string")
        return self._run(
            "install",
            {"part_number": part_number.strip()},
            on_event,
        )

    def update_index(self, on_event: EventCallback) -> Dict[str, object]:
        return self._run("update-index", {}, on_event)

    def import_pack(self, path: Path, on_event: EventCallback) -> Dict[str, object]:
        pack_path = Path(path)
        if not pack_path.is_file() or pack_path.suffix.casefold() != ".pack":
            raise ValueError("pack path must name an existing .pack file")
        return self._run(
            "import",
            {"path": str(pack_path.resolve())},
            on_event,
        )

    def _run(
        self,
        command: str,
        payload: Dict[str, object],
        on_event: EventCallback,
    ) -> Dict[str, object]:
        with self._active_lock:
            if self._phase != "idle":
                raise FlashError(FlashErrorCode.PROBE_BUSY, "pack worker is busy")
            self._active = True
            self._phase = "waiting-lock"
            self._operation_token += 1
            operation_token = self._operation_token
            self._cancel_requested = False
            self._cancel_event.clear()
        try:
            with self._root_lock.hold(
                cancel_event=self._cancel_event,
                timeout=self._lock_timeout,
            ):
                return self._run_locked(command, payload, on_event)
        finally:
            with self._active_lock:
                if self._operation_token == operation_token:
                    self._active = False
                    self._phase = "idle"
                    self._cancel_requested = False
                    self._cancel_event.clear()

    def _run_locked(
        self,
        command: str,
        payload: Dict[str, object],
        on_event: EventCallback,
    ) -> Dict[str, object]:
        with self._active_lock:
            if self._cancel_event.is_set():
                raise FlashError(FlashErrorCode.USER_ABORT, "pack operation cancelled")
            self._phase = "worker"
        result = self._worker.run(command, payload, on_event)
        with self._active_lock:
            cancelled = self._cancel_requested
            committed = getattr(self._worker, "committed_result", None)
            if not isinstance(committed, Mapping) or dict(committed) != dict(result):
                if cancelled:
                    raise FlashError(
                        FlashErrorCode.USER_ABORT, "pack operation cancelled"
                    )
            else:
                self._cancel_requested = False
            self._phase = "registering"
        if not isinstance(result, Mapping):
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack worker result must be an object",
            )
        normalized = dict(result)
        if (
            normalized.get("status") == "installed"
            and normalized.get("pack_path") is not None
        ):
            try:
                self._register_result(normalized)
            except BaseException:
                rollback = getattr(self._worker, "rollback_commit", None)
                if callable(rollback):
                    rollback(normalized)
                self._clean_staging()
                raise
        acknowledge = getattr(self._worker, "acknowledge_commit", None)
        if callable(acknowledge):
            acknowledge(normalized)
        self._clean_staging()
        return result

    def cancel(self) -> None:
        with self._active_lock:
            if self._phase not in ("waiting-lock", "worker", "removing"):
                return
            operation_token = self._operation_token
            self._cancel_requested = True
            self._cancel_event.set()
            waiting = self._phase == "waiting-lock"
            worker_active = self._phase == "worker"
        if waiting or not worker_active:
            return
        cancel = getattr(self._worker, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except FlashError:
                raise
            except Exception:
                pass
        else:
            self._terminate_worker(self._worker)
        committed = getattr(self._worker, "committed_result", None)
        if isinstance(committed, Mapping):
            return
        with self._active_lock:
            current_worker = (
                self._operation_token == operation_token and self._phase == "worker"
            )
        if current_worker:
            self._clean_staging()

    def shutdown(self) -> None:
        self.cancel()

    @staticmethod
    def _terminate_worker(worker: object) -> None:
        terminate = getattr(worker, "terminate", None)
        if not callable(terminate):
            return
        try:
            terminate()
            wait = getattr(worker, "wait", None)
            if callable(wait):
                try:
                    wait(timeout=5)
                except Exception:
                    kill = getattr(worker, "kill", None)
                    if callable(kill):
                        kill()
        except Exception:
            return

    def _clean_staging(self) -> None:
        try:
            staging = _resolved_child(
                self.paths.staging_dir,
                self.paths.root,
                "staging directory",
            )
        except FlashError:
            return
        if not staging.exists():
            return
        active_staging = getattr(self._worker, "active_staging_dir", None)
        if active_staging is not None:
            try:
                active = _resolved_child(
                    Path(active_staging), staging, "active staging directory"
                )
            except FlashError:
                return
            if active.parent == staging and active.is_dir():
                shutil.rmtree(str(active))
        else:
            for entry in staging.iterdir():
                if entry.is_file() or entry.is_symlink():
                    entry.unlink()
        try:
            staging.rmdir()
        except OSError:
            pass

    def remove(
        self,
        vendor: str,
        pack: str,
        version: str,
        in_use: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        with self._active_lock:
            if self._phase != "idle":
                raise FlashError(FlashErrorCode.PROBE_BUSY, "pack worker is busy")
            self._active = True
            self._phase = "waiting-lock"
            self._operation_token += 1
            operation_token = self._operation_token
            self._cancel_requested = False
            self._cancel_event.clear()
        try:
            with self._root_lock.hold(
                cancel_event=self._cancel_event,
                timeout=self._lock_timeout,
            ):
                with self._active_lock:
                    if self._cancel_event.is_set():
                        raise FlashError(
                            FlashErrorCode.USER_ABORT,
                            "pack operation cancelled",
                        )
                    self._phase = "removing"
                self._remove_locked(vendor, pack, version, in_use)
        finally:
            with self._active_lock:
                if self._operation_token == operation_token:
                    self._active = False
                    self._phase = "idle"
                    self._cancel_requested = False
                    self._cancel_event.clear()

    def _remove_locked(
        self,
        vendor: str,
        pack: str,
        version: str,
        in_use: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self._raise_if_cancelled()
        self._recover_root_transaction()
        if not all(isinstance(value, str) and value for value in (vendor, pack, version)):
            raise ValueError("vendor, pack, and version must be non-empty strings")
        vendor_name, pack_name, version_name, pack_id = _normalize_pack_identity(
            vendor, pack, version
        )
        if in_use is not None and in_use(pack_id, version):
            raise FlashError(FlashErrorCode.PROBE_BUSY, "pack version is in use")
        active_pack = getattr(self._worker, "active_pack", None)
        if active_pack == (pack_id, version):
            raise FlashError(FlashErrorCode.PROBE_BUSY, "pack version is in use")

        with self._state_lock:
            self._raise_if_cancelled()
            state = self._read_state()
            installed = state["installed"]
            versions = installed.get(pack_id)
            if not isinstance(versions, dict) or version not in versions:
                return
            registered = versions[version]
            if not isinstance(registered, str):
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "registered pack path must be a string",
                )
            target = _canonical_pack_path(
                self.paths, vendor_name, pack_name, version_name
            )
            registered_path = Path(registered).resolve()
            if registered_path != target:
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "registered path does not match the exact pack identity",
                )
            if target.exists() and (
                not target.is_file() or target.suffix.casefold() != ".pack"
            ):
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "registered path is not the exact pack file",
                )
            new_state = copy.deepcopy(state)
            new_versions = new_state["installed"][pack_id]
            del new_versions[version]
            if not new_versions:
                del new_state["installed"][pack_id]

            backup = None  # type: Optional[Path]
            remove_dir = None  # type: Optional[Path]
            if target.is_file():
                self._raise_if_cancelled()
                staging_root = _resolved_child(
                    self.paths.staging_dir,
                    self.paths.root,
                    "remove staging root",
                )
                staging_root.mkdir(parents=True, exist_ok=True)
                remove_dir = staging_root / ("remove-" + uuid.uuid4().hex)
                remove_dir.mkdir()
                verified_remove = _resolved_child(
                    remove_dir, staging_root, "remove staging directory"
                )
                if verified_remove.parent != staging_root:
                    raise FlashError(
                        FlashErrorCode.PACK_INTEGRITY_ERROR,
                        "remove staging must be a direct child",
                    )
                backup = verified_remove / "pack.backup"
                os.replace(str(target), str(backup))
            try:
                self._raise_if_cancelled()
                self._write_state(new_state)
            except BaseException:
                if backup is not None and backup.is_file():
                    os.replace(str(backup), str(target))
                self._cleanup_remove_staging(remove_dir)
                raise
            if backup is not None and backup.is_file():
                backup.unlink()
            self._cleanup_remove_staging(remove_dir)
            try:
                target.parent.rmdir()
            except OSError:
                pass

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise FlashError(FlashErrorCode.USER_ABORT, "pack operation cancelled")

    def _recover_root_transaction(self) -> None:
        from .pack_worker import WorkerFailure, recover_pending_transaction

        try:
            recover_pending_transaction(self.paths)
        except WorkerFailure as error:
            raise FlashError(error.code, error.message)
        except OSError as error:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "pack transaction recovery failed: {}".format(error),
            )

    def _cleanup_remove_staging(self, remove_dir: Optional[Path]) -> None:
        if remove_dir is None:
            return
        try:
            verified = _resolved_child(
                remove_dir, self.paths.staging_dir, "remove staging directory"
            )
        except FlashError:
            return
        try:
            verified.rmdir()
            self.paths.staging_dir.rmdir()
        except OSError:
            pass

    def _register_result(self, result: Mapping[str, object]) -> None:
        pack_id = result.get("pack_id")
        version = result.get("version")
        pack_path_value = result.get("pack_path")
        metadata = (pack_id, version, pack_path_value)
        if not all(isinstance(value, str) and value for value in metadata):
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "installed pack metadata is incomplete",
            )
        try:
            vendor, pack_name = str(pack_id).split(".", 1)
            expected_pack_id = vendor + "." + pack_name
            pack_path = _canonical_pack_path(
                self.paths, vendor, expected_pack_id, version
            )
        except ValueError as error:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "installed pack identity is invalid: {}".format(error),
            )
        provided_path = Path(str(pack_path_value)).resolve()
        if provided_path != pack_path:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "installed pack path does not match the exact pack identity",
            )
        if not pack_path.is_file() or pack_path.suffix.casefold() != ".pack":
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "installed pack path is not an existing .pack file",
            )
        with self._state_lock:
            state = self._read_state()
            installed = state["installed"]
            versions = installed.setdefault(str(pack_id), {})
            if not isinstance(versions, dict):
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "installed pack versions must be an object",
                )
            versions[str(version)] = str(pack_path)
            self._write_state(state)

    def _read_state(self) -> Dict[str, object]:
        if not self.paths.state_file.exists():
            return {"installed": {}}
        try:
            value = json.loads(self.paths.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "installed pack state is invalid: {}".format(error),
            )
        if not isinstance(value, dict) or not isinstance(value.get("installed"), dict):
            raise FlashError(
                FlashErrorCode.PACK_INTEGRITY_ERROR,
                "installed pack state must contain an installed object",
            )
        return value

    def _write_state(self, state: Mapping[str, object]) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.root / "state.json.{}.tmp".format(uuid.uuid4().hex)
        try:
            temporary.write_text(
                json.dumps(state, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(str(temporary), str(self.paths.state_file))
        finally:
            if temporary.exists():
                temporary.unlink()
