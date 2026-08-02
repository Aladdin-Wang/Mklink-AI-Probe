"""Artifact-only Windows lifecycle tests for the standalone Site Agent."""

from __future__ import annotations

import errno
import json
import os
import select
import socket
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from remote_package_test_support import ROOT, get_clean_package


PACKAGE_DIRECT_TOKEN_MIGRATION = (
    "direct token values are not supported; use --token-env or --token-file"
)


@pytest.fixture(scope="session")
def clean_package(tmp_path_factory):
    return get_clean_package(tmp_path_factory)


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _runtime_environment(base: Path, token: str) -> dict[str, str]:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    profile = base / "profile"
    temp = base / "temp"
    appdata = profile / "AppData" / "Roaming"
    localappdata = profile / "AppData" / "Local"
    for path in (profile, temp, appdata, localappdata):
        path.mkdir(parents=True, exist_ok=True)
    environment = {
        "SystemRoot": str(windows),
        "WINDIR": str(windows),
        "PATH": os.pathsep.join((str(windows / "System32"), str(windows))),
        "COMSPEC": str(windows / "System32" / "cmd.exe"),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "TEMP": str(temp),
        "TMP": str(temp),
        "USERPROFILE": str(profile),
        "APPDATA": str(appdata),
        "LOCALAPPDATA": str(localappdata),
        "MKLINK_REMOTE_TOKEN": token,
    }
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert "HOME" not in environment
    assert "python" not in environment["PATH"].casefold()
    assert str(ROOT).casefold() not in json.dumps(environment).casefold()
    return environment


def _last_json(text: str):
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"no structured lifecycle event in output: {text!r}")


def _control(
    executable: Path,
    runtime: Path,
    environment: dict[str, str],
    command: str,
    port: int,
):
    return subprocess.run(
        [
            str(executable),
            command,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--timeout",
            "3",
        ],
        cwd=runtime,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=_creation_flags(),
    )


def _start(
    executable: Path,
    runtime: Path,
    environment: dict[str, str],
    port: int,
    name: str,
    *,
    command: str = "start",
):
    ready_file = runtime / f"{name}-ready.json"
    log_path = runtime / f"{name}.runtime-output.txt"
    project_root = runtime / f"{name}-project"
    project_root.mkdir(exist_ok=True)
    stream = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        [
            str(executable),
            command,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ready-file",
            str(ready_file),
            "--project-root",
            str(project_root),
            "--timeout",
            "5",
        ],
        cwd=runtime,
        env=environment,
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=_creation_flags(),
    )
    return process, stream, ready_file, log_path


def _wait_ready(
    process: subprocess.Popen,
    ready_file: Path,
    log_path: Path,
    *,
    previous_pid: int | None = None,
):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if ready_file.is_file():
            try:
                payload = json.loads(ready_file.read_text("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                payload = None
            if (
                isinstance(payload, dict)
                and payload.get("event") == "ready"
                and payload.get("pid") != previous_pid
            ):
                return payload
        if process.poll() is not None:
            break
        time.sleep(0.05)
    output = (
        log_path.read_text("utf-8", errors="replace")
        if log_path.exists()
        else ""
    )
    raise AssertionError(
        f"packaged agent did not become ready; rc={process.poll()}\n{output}"
    )


def _known_process_path(pid: int) -> str | None:
    powershell = (
        Path(os.environ.get("WINDIR", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    script = (
        f"$process = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        "if ($null -eq $process) { exit 3 }; "
        "[Console]::Out.Write($process.Path)"
    )
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=_creation_flags(),
    )
    assert result.returncode in {0, 3}, result.stderr
    if result.returncode == 3:
        return None
    assert result.stdout.strip(), f"known PID {pid} has no executable path"
    return result.stdout.strip()


def _assert_known_process_gone(pid: int, executable: Path) -> None:
    observed = _known_process_path(pid)
    assert (
        observed is None
        or observed.casefold() != str(executable.resolve()).casefold()
    ), f"known packaged agent PID {pid} still runs {observed}"


def _assert_endpoint_unavailable(
    port: int,
    *,
    duration: float = 1.0,
) -> None:
    refused_codes = {
        errno.ECONNREFUSED,
        getattr(socket, "WSAECONNREFUSED", 10061),
        10061,
    }
    transient_codes = {
        getattr(errno, "EWOULDBLOCK", None),
        getattr(errno, "EINPROGRESS", None),
        getattr(errno, "EALREADY", None),
        getattr(socket, "WSAEWOULDBLOCK", 10035),
        getattr(socket, "WSAEINPROGRESS", 10036),
        getattr(socket, "WSAEALREADY", 10037),
        10035,
        10036,
        10037,
    }
    transient_codes.discard(None)
    deadline = time.monotonic() + duration
    required_observations = 2
    observations = []
    while len(observations) < required_observations:
        now = time.monotonic()
        remaining_budget = deadline - now
        remaining_observations = required_observations - len(observations)
        if remaining_budget <= 0:
            raise AssertionError(
                "endpoint probe budget expired before all independent "
                f"observations completed; got {observations} "
                f"for 127.0.0.1:{port}"
            )
        probe_window = remaining_budget / remaining_observations
        probe_deadline = now + probe_window
        status = None
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setblocking(False)
            connect_code = probe.connect_ex(("127.0.0.1", port))
            if connect_code == 0:
                raise AssertionError(
                    "expected a closed localhost TCP port, but the "
                    f"endpoint was connectable at 127.0.0.1:{port}"
                )
            if connect_code in refused_codes:
                status = "refused"
            elif connect_code not in transient_codes:
                raise AssertionError(
                    "expected a closed localhost TCP port "
                    "(connection refused), "
                    f"got connect_ex={connect_code} "
                    f"for 127.0.0.1:{port}"
                )
            else:
                probe_remaining = probe_deadline - time.monotonic()
                if probe_remaining <= 0:
                    raise AssertionError(
                        "endpoint probe window expired before connect "
                        "completion could be observed; "
                        f"connect_ex={connect_code} "
                        f"for 127.0.0.1:{port}"
                    )
                try:
                    _readable, writable, exceptional = select.select(
                        [],
                        [probe],
                        [probe],
                        probe_remaining,
                    )
                except (OSError, ValueError) as exc:
                    raise AssertionError(
                        "endpoint connect completion select failed for "
                        f"127.0.0.1:{port}: {exc}"
                    ) from exc
                if not writable and not exceptional:
                    status = "bounded_timeout"
                else:
                    completion_code = probe.getsockopt(
                        socket.SOL_SOCKET,
                        socket.SO_ERROR,
                    )
                    if completion_code == 0:
                        raise AssertionError(
                            "expected a closed localhost TCP port, but the "
                            "endpoint completed a connection at "
                            f"127.0.0.1:{port}"
                        )
                    if completion_code in refused_codes:
                        status = "refused"
                    elif completion_code in transient_codes:
                        raise AssertionError(
                            "endpoint connect completion remained ambiguous "
                            "after readiness; "
                            f"SO_ERROR={completion_code} "
                            f"for 127.0.0.1:{port}"
                        )
                    else:
                        raise AssertionError(
                            "expected a closed localhost TCP port "
                            "(connection refused), "
                            f"got SO_ERROR={completion_code} "
                            f"for 127.0.0.1:{port}"
                        )
        observations.append(status)

    assert len(observations) >= required_observations, observations
    assert all(
        status in {"refused", "bounded_timeout"} for status in observations
    ), (
        "endpoint observations must be explicit refusal or complete bounded "
        f"timeout, got {observations} for 127.0.0.1:{port}"
    )


def _assert_lifecycle_error(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 2, result.stdout + result.stderr
    event = _last_json(result.stdout)
    assert event == {
        "schema": "mklink.site-agent.lifecycle.v1",
        "event": "error",
        "error": "site agent lifecycle operation failed",
        "owned_children": 0,
    }


def _authenticated_snapshot(
    executable: Path,
    runtime: Path,
    environment: dict[str, str],
    port: int,
    ready_file: Path,
    expected_pid: int,
) -> dict:
    ready_state = json.loads(ready_file.read_text("utf-8"))
    assert ready_state["schema"] == "mklink.site-agent.lifecycle.v1"
    assert ready_state["event"] == "ready"
    assert ready_state["ready"] is True
    assert ready_state["port"] == port
    assert int(ready_state["pid"]) == expected_pid
    assert ready_state["probe_connected"] is False
    assert ready_state["owned_children"] == 0

    health = _control(
        executable,
        runtime,
        environment,
        "health",
        port,
    )
    assert health.returncode == 0, health.stdout + health.stderr
    health_event = _last_json(health.stdout)
    assert health_event == {
        "schema": "mklink.site-agent.lifecycle.v1",
        "event": "health",
        "result": {
            "listener": True,
            "probe_connected": False,
            "ready": True,
        },
        "owned_children": 0,
    }

    status = _control(
        executable,
        runtime,
        environment,
        "status",
        port,
    )
    assert status.returncode == 0, status.stdout + status.stderr
    status_event = _last_json(status.stdout)
    assert status_event["schema"] == "mklink.site-agent.lifecycle.v1"
    assert status_event["event"] == "status"
    assert status_event["owned_children"] == 0
    status_result = status_event["result"]
    stable_status = {
        "host": status_result["host"],
        "port": status_result["port"],
        "ready": status_result["ready"],
        "listener": status_result["listener"],
        "probe_connected": status_result["probe_connected"],
        "device_state": status_result["device_state"],
        "last_error": status_result["last_error"],
        "resources": status_result["resources"],
    }
    assert stable_status == {
        "host": "127.0.0.1",
        "port": port,
        "ready": True,
        "listener": True,
        "probe_connected": False,
        "device_state": "disconnected",
        "last_error": None,
        "resources": {},
    }
    assert status_result == stable_status
    return {
        "identity": {
            "pid": int(ready_state["pid"]),
            "host": ready_state["host"],
            "port": ready_state["port"],
        },
        "health": health_event,
        "status": {
            "schema": status_event["schema"],
            "event": status_event["event"],
            "owned_children": status_event["owned_children"],
            "result": stable_status,
        },
    }


def _authenticated_pair_snapshots(
    executable: Path,
    runtime: Path,
    target_environment: dict[str, str],
    target_port: int,
    target_ready_file: Path,
    target_pid: int,
    neighbor_environment: dict[str, str],
    neighbor_port: int,
    neighbor_ready_file: Path,
    neighbor_pid: int,
) -> dict:
    return {
        "target": _authenticated_snapshot(
            executable,
            runtime,
            target_environment,
            target_port,
            target_ready_file,
            target_pid,
        ),
        "neighbor": _authenticated_snapshot(
            executable,
            runtime,
            neighbor_environment,
            neighbor_port,
            neighbor_ready_file,
            neighbor_pid,
        ),
    }


def _stop_if_running(executable, runtime, environment, port, process):
    if process is None or process.poll() is not None:
        return
    try:
        _control(executable, runtime, environment, "stop", port)
        process.wait(timeout=10)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _assert_obsolete_token_rejection(
    executable: Path,
    runtime: Path,
    environment: dict[str, str],
):
    ready_file = runtime / "obsolete-token-ready-must-not-exist.json"
    project_root = runtime / "obsolete-token-project-must-not-exist"
    observed_processes = []
    for spelling in ("separate", "equals"):
        sentinel = f"packaged-direct-token-{spelling}"
        obsolete = (
            ["--token", sentinel]
            if spelling == "separate"
            else [f"--token={sentinel}"]
        )
        process = subprocess.Popen(
            [
                str(executable),
                "start",
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--ready-file",
                str(ready_file),
                "--project-root",
                str(project_root),
                *obsolete,
            ],
            cwd=runtime,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creation_flags(),
        )
        observed_processes.append(process)
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
            pytest.fail(
                "obsolete direct-token rejection did not terminate before "
                f"operation: stdout={stdout!r}, stderr={stderr!r}"
            )
        assert process.returncode == 2
        assert stdout == ""
        assert sentinel not in stderr
        assert stderr.count(PACKAGE_DIRECT_TOKEN_MIGRATION) == 1
        assert not ready_file.exists()
        assert not project_root.exists()
        assert process.poll() == 2
        _assert_known_process_gone(process.pid, executable)
    assert all(process.poll() == 2 for process in observed_processes)


def test_lifecycle_clean_environment_target_restart_neighbor_and_cleanup(
    clean_package, tmp_path
):
    runtime = tmp_path / "artifact-runtime"
    runtime.mkdir()
    with zipfile.ZipFile(clean_package["artifact"]) as archive:
        archive.extractall(runtime)
    package_root = runtime / "mklink-remote-agent"
    executable = package_root / "mklink-remote-agent.exe"
    assert executable.is_file()
    assert not any(path.suffix.casefold() == ".py" for path in package_root.rglob("*"))
    assert not (package_root / "skills").exists()
    assert not (package_root / ".git").exists()

    target_token = "target-token-4t1"
    neighbor_token = "neighbor-token-4t1"
    target_env = _runtime_environment(runtime / "target-env", target_token)
    neighbor_env = _runtime_environment(runtime / "neighbor-env", neighbor_token)
    _assert_obsolete_token_rejection(
        executable,
        runtime,
        target_env,
    )
    wrong_env = dict(target_env)
    wrong_env["MKLINK_REMOTE_TOKEN"] = "wrong-token-4t1"
    target_token_against_neighbor_env = dict(neighbor_env)
    target_token_against_neighbor_env["MKLINK_REMOTE_TOKEN"] = target_token
    neighbor_token_against_target_env = dict(target_env)
    neighbor_token_against_target_env["MKLINK_REMOTE_TOKEN"] = neighbor_token
    target_port = _free_port()
    neighbor_port = _free_port()
    while neighbor_port == target_port:
        neighbor_port = _free_port()

    target = neighbor = replacement = None
    streams = []
    try:
        target, target_stream, target_ready_file, target_log = _start(
            executable,
            runtime,
            target_env,
            target_port,
            "target",
        )
        streams.append(target_stream)
        target_ready = _wait_ready(target, target_ready_file, target_log)
        neighbor, neighbor_stream, neighbor_ready_file, neighbor_log = _start(
            executable,
            runtime,
            neighbor_env,
            neighbor_port,
            "neighbor",
        )
        streams.append(neighbor_stream)
        neighbor_ready = _wait_ready(neighbor, neighbor_ready_file, neighbor_log)

        for ready, port in (
            (target_ready, target_port),
            (neighbor_ready, neighbor_port),
        ):
            assert ready["schema"] == "mklink.site-agent.lifecycle.v1"
            assert ready["ready"] is True
            assert ready["port"] == port
            assert ready["probe_connected"] is False
            assert ready["owned_children"] == 0

        original_target_pid = int(target_ready["pid"])
        original_neighbor_pid = int(neighbor_ready["pid"])
        assert target.pid == original_target_pid
        assert neighbor.pid == original_neighbor_pid

        def authenticated_original_pair() -> dict:
            return _authenticated_pair_snapshots(
                executable,
                runtime,
                target_env,
                target_port,
                target_ready_file,
                original_target_pid,
                neighbor_env,
                neighbor_port,
                neighbor_ready_file,
                original_neighbor_pid,
            )

        authenticated_before_cross_tokens = authenticated_original_pair()

        target_token_against_neighbor = _control(
            executable,
            runtime,
            target_token_against_neighbor_env,
            "health",
            neighbor_port,
        )
        _assert_lifecycle_error(target_token_against_neighbor)
        assert (
            authenticated_original_pair()
            == authenticated_before_cross_tokens
        )
        neighbor_token_against_target = _control(
            executable,
            runtime,
            neighbor_token_against_target_env,
            "health",
            target_port,
        )
        _assert_lifecycle_error(neighbor_token_against_target)
        assert (
            authenticated_original_pair()
            == authenticated_before_cross_tokens
        )
        assert target.poll() is None
        assert neighbor.poll() is None
        assert int(json.loads(target_ready_file.read_text("utf-8"))["pid"]) == (
            original_target_pid
        )
        assert int(json.loads(neighbor_ready_file.read_text("utf-8"))["pid"]) == (
            original_neighbor_pid
        )

        wrong_stop = _control(
            executable, runtime, wrong_env, "stop", target_port
        )
        _assert_lifecycle_error(wrong_stop)
        assert (
            authenticated_original_pair()
            == authenticated_before_cross_tokens
        )
        assert target.poll() is None

        wrong_restart = _control(
            executable, runtime, wrong_env, "restart", target_port
        )
        _assert_lifecycle_error(wrong_restart)
        assert (
            authenticated_original_pair()
            == authenticated_before_cross_tokens
        )
        assert target.poll() is None
        assert int(json.loads(target_ready_file.read_text("utf-8"))["pid"]) == (
            original_target_pid
        )
        assert neighbor.poll() is None

        replacement, replacement_stream, _ready, replacement_log = _start(
            executable,
            runtime,
            target_env,
            target_port,
            "target",
            command="restart",
        )
        streams.append(replacement_stream)
        replacement_ready = _wait_ready(
            replacement,
            target_ready_file,
            replacement_log,
            previous_pid=original_target_pid,
        )
        target.wait(timeout=15)
        assert target.returncode == 0
        _assert_known_process_gone(original_target_pid, executable)
        assert replacement_ready["pid"] != original_target_pid
        assert replacement_ready["pid"] == replacement.pid
        assert replacement_ready["owned_children"] == 0
        assert neighbor.poll() is None
        assert int(json.loads(neighbor_ready_file.read_text("utf-8"))["pid"]) == (
            original_neighbor_pid
        )
        neighbor_health = _control(
            executable, runtime, neighbor_env, "health", neighbor_port
        )
        assert neighbor_health.returncode == 0
        target_health = _control(
            executable, runtime, target_env, "health", target_port
        )
        assert target_health.returncode == 0
        replacement_status = _control(
            executable, runtime, target_env, "status", target_port
        )
        assert replacement_status.returncode == 0
        assert _last_json(replacement_status.stdout)["owned_children"] == 0
        neighbor_status = _control(
            executable, runtime, neighbor_env, "status", neighbor_port
        )
        assert neighbor_status.returncode == 0
        assert _last_json(neighbor_status.stdout)["owned_children"] == 0

        stopped = _control(
            executable, runtime, target_env, "stop", target_port
        )
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        replacement.wait(timeout=15)
        assert replacement.returncode == 0
        _assert_known_process_gone(replacement.pid, executable)
        assert not target_ready_file.exists()
        _assert_endpoint_unavailable(target_port)
        assert neighbor.poll() is None
        assert int(json.loads(neighbor_ready_file.read_text("utf-8"))["pid"]) == (
            original_neighbor_pid
        )
        assert _control(
            executable, runtime, neighbor_env, "health", neighbor_port
        ).returncode == 0

        neighbor_stopped = _control(
            executable, runtime, neighbor_env, "stop", neighbor_port
        )
        assert neighbor_stopped.returncode == 0
        neighbor.wait(timeout=15)
        assert neighbor.returncode == 0
        _assert_known_process_gone(original_neighbor_pid, executable)
        assert not neighbor_ready_file.exists()
        assert target.poll() == 0
        assert replacement.poll() == 0
        assert neighbor.poll() == 0
        _assert_endpoint_unavailable(target_port)
        _assert_endpoint_unavailable(neighbor_port)
    finally:
        _stop_if_running(
            executable, runtime, target_env, target_port, replacement
        )
        _stop_if_running(
            executable, runtime, target_env, target_port, target
        )
        _stop_if_running(
            executable, runtime, neighbor_env, neighbor_port, neighbor
        )
        for stream in streams:
            stream.close()
