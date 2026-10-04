"""Per-user CDC runtime discovery and clients (no hardware in client processes)."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

PROTOCOL = 37  # FLM-only copies use the shared deployment journal.
VERSION = "0.3.0"


class RuntimeErrorResponse(RuntimeError):
    def __init__(self, message, *, status_code=None, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = message if detail is None else detail


def runtime_dir(probe_id=None) -> Path:
    override = os.environ.get("MKLINK_RUNTIME_DIR")
    if override:
        root = Path(override).resolve()
    else:
        from mklink.web_entry import platform_data_dir
        root = platform_data_dir().parent / "runtime"
    if probe_id is not None:
        import re
        if not re.fullmatch(r"(?:usb-|local-)[0-9a-f]{24}|lobby", probe_id):
            raise RuntimeErrorResponse("Invalid probe identity")
        root = root / "probes" / probe_id
    return root


def _private_dir(probe_id=None) -> Path:
    root = runtime_dir(probe_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    return root


@contextmanager
def runtime_lock(name: str, probe_id=None):
    """OS-owned lock: process death releases ownership, stale JSON does not."""
    path = _private_dir(probe_id) / name
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), "r+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeErrorResponse("Shared runtime is starting or already running; retry shortly") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def request(info: dict, method: str, path: str, payload=None, *, timeout=35, form=False):
    port = info.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise RuntimeErrorResponse("Invalid runtime endpoint")
    if form:
        from urllib.parse import urlencode
        data = urlencode(payload).encode('utf-8')
    else:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"X-Auth-Token": info["token"], "Content-Type":
               "application/x-www-form-urlencoded" if form else "application/json"}
    req = Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method)
    # Local IPC must never travel through environment-configured HTTP proxies.
    try:
        with build_opener(ProxyHandler({})).open(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read(65536).decode("utf-8", "replace")
        try:
            body = json.loads(detail)
            structured_detail = body.get("detail") if isinstance(body, dict) else None
        except ValueError:
            structured_detail = None
        raise RuntimeErrorResponse(f"Runtime HTTP {exc.code}: {detail}",
                                   status_code=exc.code, detail=structured_detail) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeErrorResponse("Shared runtime is unavailable; no direct CDC fallback was attempted") from exc


def discover(probe_id=None) -> dict | None:
    if probe_id is None:
        entries = running_runtimes()
        if len(entries) > 1:
            raise RuntimeErrorResponse("Multiple runtimes are running; select a probe explicitly")
        return entries[0] if entries else None
    try:
        info = json.loads((runtime_dir(probe_id) / "endpoint.json").read_text(encoding="utf-8"))
        health = request(info, "GET", "/_runtime/status", timeout=1)
    except (OSError, ValueError, KeyError, RuntimeErrorResponse):
        return None
    if health.get("instance_id") != info.get("instance_id"):
        return None
    if health.get("protocol") != PROTOCOL or health.get("version") != VERSION:
        raise RuntimeErrorResponse("Runtime version differs; stop the old runtime explicitly before upgrading")
    return info


def running_runtimes() -> list[dict]:
    result = []
    for path in (runtime_dir() / "probes").glob("*/endpoint.json"):
        info = discover(path.parent.name)
        if info:
            result.append(info)
    return result


def selected_runtime(selector=None) -> dict | None:
    """Permit stopping an unplugged probe by stable ID or saved alias."""
    if not selector:
        return discover()
    from mklink.probes import load_aliases, select_probe
    aliases = load_aliases()
    for info in running_runtimes():
        if str(selector).casefold() in {info["probe_id"].casefold(), aliases.get(info["probe_id"], "").casefold()}:
            return info
    return discover(select_probe(selector)["probe_id"])


def ensure_runtime(*, project_root: str = ".", port: int = 8765, probe=None, device_port=None, allow_lobby=False) -> dict:
    from mklink.probes import select_probe
    selected = select_probe(probe or device_port, allow_lobby=allow_lobby)
    probe_id = selected["probe_id"]
    info = discover(probe_id)
    if info:
        return info
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            with runtime_lock("startup.lock", probe_id):
                info = discover(probe_id)
                if info:
                    return info
                # HTTP can disappear before shutdown finishes closing the
                # device and diagnostics. Wait using the existing owner lock
                # before spawning a replacement that would immediately exit.
                with runtime_lock("owner.lock", probe_id):
                    pass
                root = _private_dir(probe_id)
                command = [sys.executable]
                if not getattr(sys, "frozen", False):
                    command += ["-m", "mklink"]
                command += ["runtime", "serve", "--project-root", str(Path(project_root).resolve()), "--port", str(port), "--probe-id", probe_id]
                kwargs = {"cwd": str(Path(__file__).resolve().parent.parent), "stdin": subprocess.DEVNULL}
                if os.name == "nt":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.environ.get("MKLINK_PARENT_JOB_BREAKAWAY_OK") == "1":
                        kwargs["creationflags"] |= subprocess.CREATE_BREAKAWAY_FROM_JOB
                else:
                    kwargs["start_new_session"] = True
                environment = dict(os.environ)
                if getattr(sys, "frozen", False):
                    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                    # The detached runtime must not hold the launching onefile
                    # process's temporary extraction directory open on Windows.
                    kwargs["cwd"] = str(root)
                # A detached runtime must not inherit a build wrapper's short-lived TEMP.
                scratch = root / "tmp"
                scratch.mkdir(exist_ok=True)
                environment.update(TEMP=str(scratch), TMP=str(scratch), TMPDIR=str(scratch))
                kwargs["env"] = environment
                # Only pre-server/native diagnostics use the inherited handle.
                # The server owns and rotates its Python diagnostics separately.
                with (root / "startup.log").open("wb") as output:
                    process = subprocess.Popen(command, stdout=output, stderr=output, **kwargs)
                while time.monotonic() < deadline:
                    info = discover(probe_id)
                    if info:
                        return info
                    if process.poll() is not None:
                        raise RuntimeErrorResponse(f"Runtime startup failed; inspect {root / 'runtime.log'} and {root / 'startup.log'}")
                    time.sleep(0.2)
                raise RuntimeErrorResponse("Runtime startup timed out; do not open CDC independently")
        except RuntimeErrorResponse as exc:
            if "starting or already running" not in str(exc):
                raise
            time.sleep(0.2)
    raise RuntimeErrorResponse("Timed out waiting for runtime startup")


def browser_url(info: dict, *, page: str = "config") -> str:
    if page not in {"config", "vofa", "serial"}:
        raise ValueError("Unsupported runtime browser page")
    query = f"?page={page}" if page != "config" else ""
    # Fragment is not sent in HTTP requests or access logs; login clears it.
    return f"http://127.0.0.1:{info['port']}/_runtime/open{query}#{info['token']}"


def query_probe(capability, *, info=None, probe=None, port=None):
    """One probe-only query; never attach/initialize a target or retry a command."""
    from mklink.runtime_capabilities import PROBE_QUERIES
    if capability not in PROBE_QUERIES:
        raise ValueError('Unsupported probe query')
    if info is not None and (probe or port):
        raise ValueError('Specify an existing runtime or a probe selector, not both')
    if info is None:
        info = ensure_runtime(probe=probe, device_port=port)
    return request(info, 'POST', PROBE_QUERIES[capability], {})


def job_status(info, job_id=None):
    """Query a retained result without attaching or reconnecting hardware."""
    if info is None:
        raise RuntimeErrorResponse('Select a runtime first')
    if job_id is not None and (not isinstance(job_id, str) or len(job_id) != 32
                               or any(c not in '0123456789abcdef' for c in job_id)):
        raise ValueError('Invalid job ID')
    return request(info, 'GET', '/api/runtime/jobs/' + (job_id or ''))


class RuntimeClient:
    """One explicit session; serialize its requests against attach and detach.

    This lock protects client lifecycle, not hardware admission. Other clients
    and the renewal thread remain independent; the backend owns resource policy.
    """

    def __init__(self, *, project_root=".", info=None, kind='mcp', name='AI client'):
        self.info = info
        self.project_root = project_root
        self.session_id = None
        self._stop = threading.Event()
        self._heartbeat = None
        self._lock = threading.Lock()
        self.kind, self.name = kind, name

    def connect(self, *, project_root=None, port=None, probe=None, axf=None, mcu=None, elf_backend=None, scope='target'):
        if scope not in ('target', 'uart'):
            raise ValueError('Session scope must be target or uart')
        if scope == 'uart' and any(value is not None for value in (port, axf, mcu, elf_backend)):
            raise ValueError('UART-only attachment accepts a probe selector, not target connection settings')
        with self._lock:
            if self.info is None:
                options = {'allow_lobby': True} if scope == 'uart' else {}
                self.info = ensure_runtime(project_root=project_root or self.project_root, probe=probe, device_port=port, **options)
            elif probe or port:
                from mklink.probes import select_probe
                if select_probe(probe or port, allow_lobby=scope == 'uart')["probe_id"] != self.info.get("probe_id"):
                    raise RuntimeErrorResponse("This client is bound to another probe; disconnect and create a new client")
            result = request(self.info, "POST", "/_runtime/attach", {
                "project_root": project_root, "port": port, "axf": axf,
                "mcu": mcu, "elf_backend": elf_backend, "session_id": self.session_id,
                'kind': self.kind, 'name': self.name, 'scope': scope,
            })
            self.session_id = result["session_id"]
            self._stop_heartbeat()
            # Never reuse a stop signal or session snapshot from an older
            # attachment, even if its timed-out renewal is still returning.
            self._stop = threading.Event()
            self._heartbeat = threading.Thread(target=self._renew, args=(self._stop, self.session_id),
                                               daemon=True, name="runtime-session")
            self._heartbeat.start()
            return result

    def _stop_heartbeat(self):
        self._stop.set()
        if self._heartbeat and self._heartbeat is not threading.current_thread():
            self._heartbeat.join(timeout=6)

    def _renew(self, stop, session_id):
        while not stop.wait(20):
            try:
                request(self.info, "POST", "/_runtime/heartbeat", {"session_id": session_id}, timeout=5)
            except RuntimeErrorResponse:
                # Do not silently reconnect/replay a command after loss of ownership.
                return

    def call(self, capability: str, arguments=None):
        with self._lock:
            if not self.session_id:
                raise RuntimeErrorResponse("Call connect first")
            transport_options = {}
            if capability == 'flush_memory':
                from mklink.memory_write import validate_writes, plan_flush_batches
                args = arguments or {}
                batches = plan_flush_batches(validate_writes(args.get('writes')))
                # Every command can consume its 10s budget; verified readbacks
                # also need time. Timeout never causes a replay.
                reads = sum((len(data) + 4095) // 4096 for batch in batches for _, data in batch)
                transport_options['timeout'] = max(35, 10 * (len(batches) + reads) + 15)
            if capability == 'dump_memory':
                from mklink.dump_memory import validate_dump_capture
                args = arguments or {}
                validate_dump_capture(args.get('regions'), args.get('sample_count', 1),
                                      args.get('timeout', 10.0), args.get('speed_profile'))
                # Cover every explicit sample plus the bridge's confirmed-stop
                # budget. A slow capture must not inherit the default 35s HTTP limit.
                transport_options['timeout'] = max(35, args.get('sample_count', 1) * (args.get('timeout', 10.0) + 5) + 15)
            if capability == 'measure_dump_memory':
                from mklink.dump_benchmark import measurement_regions, validate_measurement
                args = arguments or {}
                validate_measurement(measurement_regions(args.get('regions')), args.get('duration', 3.0),
                                     args.get('period', 0.000001), args.get('speed_profile'))
                transport_options['timeout'] = max(35, args.get('duration', 3.0) + 20)
            if capability == 'capture_dump':
                from mklink.dump_memory import validate_dump_stream
                args = arguments or {}
                validate_dump_stream(args.get('regions'), args.get('period', 0.0), args.get('frames', 1),
                                     args.get('duration', 2.0), args.get('speed_profile'))
                transport_options['timeout'] = max(35, (args.get('duration', 2.0) or 300) + 20)
            return request(self.info, "POST", "/_runtime/call", {
                "session_id": self.session_id, "capability": capability, "arguments": arguments or {},
            }, **transport_options)

    def start_job(self, action, *, request_id, confirm=False, arguments=None):
        """Submit once with this session; the backend owns validation and deduplication."""
        with self._lock:
            if self.info is None or not self.session_id:
                raise RuntimeErrorResponse('Connect to the selected probe first')
            return request(self.info, 'POST', '/api/runtime/jobs/', {
                'action': action, 'request_id': request_id, 'confirm': confirm,
                'arguments': arguments if arguments is not None else {}, 'session_id': self.session_id})

    def job_status(self, job_id=None):
        return job_status(self.info, job_id)

    def close(self):
        with self._lock:
            session_id = self.session_id
            # A lost detach response must not leave this client able to send
            # commands on a session it has already relinquished locally.
            self.session_id = None
            self._stop_heartbeat()
            if session_id:
                request(self.info, "POST", "/_runtime/detach", {"session_id": session_id})


def serve_runtime(*, project_root=".", port=8765, probe_id="lobby"):
    from mklink.runtime_logging import runtime_diagnostics
    with runtime_lock("owner.lock", probe_id), runtime_diagnostics(_private_dir(probe_id)):
        _serve_runtime(project_root=project_root, port=port, probe_id=probe_id)


def _serve_runtime(*, project_root, port, probe_id):
    from mklink.probes import bind_runtime
    bind_runtime(probe_id)
    import uvicorn
    from mklink.remote.api import create_app
    from mklink.runtime_api import install_runtime
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        info = {"port": listener.getsockname()[1], "token": secrets.token_urlsafe(32),
                "instance_id": secrets.token_hex(16), "protocol": PROTOCOL, "version": VERSION, "pid": os.getpid(),
                "probe_id": probe_id}
        info['jobs_path'] = str(_private_dir(probe_id) / 'jobs.json')
        app = create_app(project_root=str(Path(project_root).resolve()), backend_port=info["port"])
        control = install_runtime(app, info)
        from mklink.observe_bridge import configure_stream_observation
        configure_stream_observation(app, host="127.0.0.1", port=info["port"],
                                     auth_token=info["token"], private_correlation=info["instance_id"])
        server = uvicorn.Server(uvicorn.Config(app, log_level="info", access_log=False,
                                              ws="websockets-sansio", ws_per_message_deflate=False))
        control.shutdown = lambda: setattr(server, "should_exit", True)
        path = _private_dir(probe_id) / "endpoint.json"
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(info, output)
        temporary.replace(path)
        try:
            server.run(sockets=[listener])
        finally:
            path.unlink(missing_ok=True)
    finally:
        listener.close()
