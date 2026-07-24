import json
import os
import sys
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from mklink import web_entry


def test_protocol_uri_accepts_only_the_web_entry_actions():
    assert web_entry.parse_protocol_uri("mklink-ai-probe://web/start") == "start"
    assert web_entry.parse_protocol_uri("mklink-ai-probe://web/open") == "open"
    assert web_entry.parse_protocol_uri("mklink-ai-probe://web/stop") == "stop"

    for uri in (
        "https://example.com/web/start",
        "mklink-ai-probe://shell/start",
        "mklink-ai-probe://web/run?command=calc",
        "mklink-ai-probe://web/../../start",
    ):
        with pytest.raises(web_entry.WebEntryError):
            web_entry.parse_protocol_uri(uri)


def test_launcher_html_is_one_offline_file_with_cross_platform_protocol_links(tmp_path):
    output = tmp_path / "MKLink-Web.html"

    web_entry.write_launcher_html(output, icon_data_uri="data:image/png;base64,AA==")

    html = output.read_text(encoding="utf-8")
    assert "mklink-ai-probe://web/start" in html
    assert "mklink-ai-probe://web/stop" in html
    assert "data:image/png;base64,AA==" in html
    assert "http://" not in html
    assert "https://" not in html
    assert list(tmp_path.iterdir()) == [output]


@pytest.mark.parametrize(
    ("system", "environment", "home", "suffix"),
    [
        ("Windows", {"LOCALAPPDATA": r"C:\Users\test\AppData\Local"}, Path("C:/Users/test"), "Mklink AI Probe/web-entry"),
        ("Darwin", {}, Path("/Users/test"), "Library/Application Support/Mklink AI Probe/web-entry"),
        ("Linux", {"XDG_DATA_HOME": "/home/test/.data"}, Path("/home/test"), "mklink-ai-probe/web-entry"),
    ],
)
def test_platform_data_directory_is_user_scoped(system, environment, home, suffix):
    path = web_entry.platform_data_dir(system=system, environment=environment, home=home)
    assert str(path).replace("\\", "/").endswith(suffix)


def test_generated_handler_pins_the_installed_skill_root(tmp_path):
    script = web_entry.render_handler_script(tmp_path / "skill root")

    assert repr(str((tmp_path / "skill root").resolve())) in script
    assert "protocol_handler_main" in script
    assert "sys.path.insert" in script


def test_linux_desktop_handler_uses_the_same_uri_scheme(tmp_path):
    desktop = web_entry.render_linux_desktop_entry(
        Path("/opt/mklink/python3"), tmp_path / "handler.py",
    )

    assert "MimeType=x-scheme-handler/mklink-ai-probe;" in desktop
    assert "Terminal=false" in desktop
    assert "%u" in desktop


def test_linux_desktop_handler_escapes_field_codes_and_special_characters(tmp_path):
    desktop = web_entry.render_linux_desktop_entry(
        PurePosixPath("/opt/MKLink $runtime/python3"),
        PurePosixPath("/home/user/100% handler.py"),
    )

    assert '"/opt/MKLink \\$runtime/python3"' in desktop
    assert "100%% handler.py" in desktop


def test_macos_info_plist_registers_the_same_uri_scheme():
    document = web_entry.macos_info_plist()

    assert document["CFBundleIdentifier"] == "com.microkeen.mklink-ai-probe.web-entry"
    schemes = document["CFBundleURLTypes"][0]["CFBundleURLSchemes"]
    assert schemes == ["mklink-ai-probe"]


def test_macos_launcher_shell_quotes_runtime_and_handler_paths(tmp_path):
    script = web_entry.render_macos_launcher(
        PurePosixPath("/Users/O'Brien/MKLink $runtime/python3"),
        PurePosixPath("/Users/test/handler.py"),
    )

    assert "exec '/Users/O'\"'\"'Brien/MKLink $runtime/python3'" in script
    assert "'$1'" not in script
    assert '"$1"' in script


def test_windows_registry_command_uses_an_absolute_handler_and_quoted_uri(tmp_path):
    command = web_entry.windows_registry_command(
        Path(r"C:\Python\pythonw.exe"), tmp_path / "handler.py",
    )

    assert "pythonw.exe" in command
    assert str(tmp_path / "handler.py") in command
    assert '"%1"' in command


def test_gui_server_command_reuses_the_existing_cli_without_touching_mcp_or_serve(tmp_path):
    executable = Path("python3")
    command = web_entry.gui_server_command(
        port=8771,
        executable=executable,
        repository_root=tmp_path,
        project_root=tmp_path / "runtime workspace",
    )

    assert command[:4] == [str(executable), "-m", "mklink", "gui"]
    assert "--no-browser" in command
    assert "--port" in command and "8771" in command
    assert command[command.index("--project-root") + 1] == str(tmp_path / "runtime workspace")
    assert "serve" not in command
    assert "mcp" not in command


def test_web_entry_url_changes_with_the_frontend_build(tmp_path):
    dist = tmp_path / "gui" / "dist"
    dist.mkdir(parents=True)
    index = dist / "index.html"
    index.write_text("old", encoding="utf-8")
    old_url = web_entry.web_entry_url(8765, root=tmp_path)

    index.write_text("new", encoding="utf-8")
    new_url = web_entry.web_entry_url(8765, root=tmp_path)

    assert old_url.startswith("http://127.0.0.1:8765/?build=")
    assert old_url.endswith("#/config")
    assert new_url != old_url


def test_start_reuses_an_existing_web_server_without_spawning_or_owning_it(tmp_path):
    spawned = []
    opened = []

    result = web_entry.start_web_entry(
        data_dir=tmp_path,
        probe=lambda port: "web" if port == 8765 else None,
        port_available=lambda _port: False,
        spawn=lambda *_args, **_kwargs: spawned.append(True),
        browser_open=opened.append,
    )

    assert result == {"status": "reused", "port": 8765, "owned": False}
    assert spawned == []
    assert opened == [web_entry.web_entry_url(8765)]
    assert not (tmp_path / "state.json").exists()


def test_start_scans_the_port_range_before_starting_a_competing_backend(tmp_path):
    opened = []

    result = web_entry.start_web_entry(
        data_dir=tmp_path,
        probe=lambda port: "web" if port == 8766 else None,
        port_available=lambda port: port == 8765,
        spawn=lambda *_args, **_kwargs: pytest.fail("must reuse the existing Web service"),
        browser_open=opened.append,
    )

    assert result == {"status": "reused", "port": 8766, "owned": False}
    assert opened == [web_entry.web_entry_url(8766)]


def test_start_refuses_to_compete_with_a_running_mklink_api_without_web_assets(tmp_path):
    with pytest.raises(web_entry.WebEntryError, match="already running"):
        web_entry.start_web_entry(
            data_dir=tmp_path,
            probe=lambda port: "api" if port == 8765 else None,
            port_available=lambda _port: False,
            spawn=lambda *_args, **_kwargs: None,
            browser_open=lambda _url: None,
        )


def test_start_spawns_one_owned_gui_and_stop_only_terminates_that_pid(tmp_path):
    probes = {8765: [None, None, "web"]}
    terminated = []
    opened = []
    commands = []

    def probe(port):
        values = probes.get(port, [None])
        return values.pop(0) if len(values) > 1 else values[0]

    def spawn(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(pid=4321)

    result = web_entry.start_web_entry(
        data_dir=tmp_path,
        probe=probe,
        port_available=lambda port: port == 8765,
        spawn=spawn,
        browser_open=opened.append,
        sleep=lambda _seconds: None,
        timeout=1,
        process_identity=lambda pid: f"process-{pid}",
    )

    assert result == {"status": "started", "port": 8765, "owned": True, "pid": 4321}
    assert commands and "gui" in commands[0]
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["pid"] == 4321 and state["owned"] is True

    stopped = web_entry.stop_web_entry(
        data_dir=tmp_path,
        terminate=terminated.append,
        process_identity=lambda pid: f"process-{pid}",
    )
    assert stopped == {"status": "stopped", "port": 8765, "pid": 4321}
    assert terminated == [4321]
    assert not (tmp_path / "state.json").exists()


def test_stop_does_not_kill_a_reused_pid_from_stale_state(tmp_path):
    terminated = []
    (tmp_path / "state.json").write_text(json.dumps({
        "pid": 4321,
        "port": 8765,
        "owned": True,
        "process_identity": "old-process",
    }), encoding="utf-8")

    result = web_entry.stop_web_entry(
        data_dir=tmp_path,
        terminate=terminated.append,
        process_identity=lambda _pid: "new-process",
    )

    assert result == {"status": "stale", "port": 8765, "pid": 4321}
    assert terminated == []
    assert not (tmp_path / "state.json").exists()


def test_stop_never_terminates_a_reused_or_missing_service(tmp_path):
    terminated = []
    (tmp_path / "state.json").write_text(json.dumps({
        "pid": 999, "port": 8765, "owned": False,
    }), encoding="utf-8")

    result = web_entry.stop_web_entry(
        data_dir=tmp_path,
        terminate=terminated.append,
    )

    assert result["status"] == "not_owned"
    assert terminated == []


def test_protocol_handler_dispatches_start_open_and_stop(monkeypatch, tmp_path):
    starts = []
    stops = []
    monkeypatch.setattr(web_entry, "platform_data_dir", lambda: tmp_path)
    monkeypatch.setattr(web_entry, "start_web_entry", lambda **kwargs: starts.append(kwargs) or {"status": "started"})
    monkeypatch.setattr(web_entry, "stop_web_entry", lambda **kwargs: stops.append(kwargs) or {"status": "stopped"})

    assert web_entry.handle_protocol_uri("mklink-ai-probe://web/start")["status"] == "started"
    assert web_entry.handle_protocol_uri("mklink-ai-probe://web/open")["status"] == "started"
    assert web_entry.handle_protocol_uri("mklink-ai-probe://web/stop")["status"] == "stopped"
    assert len(starts) == 2
    assert len(stops) == 1
    assert starts[0]["data_dir"] == tmp_path


def test_process_identity_is_stable_for_the_current_process():
    first = web_entry.get_process_identity(os.getpid())
    second = web_entry.get_process_identity(os.getpid())

    assert first
    assert second == first
    assert web_entry.get_process_identity(-1) is None


def test_linux_install_creates_a_user_desktop_handler(tmp_path):
    result = web_entry.install_protocol(
        system="Linux",
        data_dir=tmp_path / "data",
        home=tmp_path / "home",
        environment={"XDG_DATA_HOME": str(tmp_path / "share")},
        python_executable=Path("/opt/mklink/python3"),
        runner=lambda *_args, **_kwargs: None,
    )

    desktop = Path(result["registration"])
    assert desktop == tmp_path / "share" / "applications" / "mklink-ai-probe-web.desktop"
    assert desktop.is_file()
    assert (tmp_path / "data" / "handler.py").is_file()


def test_macos_install_creates_a_user_application_bundle(tmp_path):
    result = web_entry.install_protocol(
        system="Darwin",
        data_dir=tmp_path / "data",
        home=tmp_path / "home",
        environment={},
        python_executable=Path("/opt/mklink/python3"),
        runner=lambda *_args, **_kwargs: None,
    )

    app = Path(result["registration"])
    assert app == tmp_path / "home" / "Applications" / "Mklink AI Probe Web Launcher.app"
    assert (app / "Contents" / "Info.plist").is_file()
    assert (app / "Contents" / "MacOS" / "mklink-web-entry").is_file()


def test_windows_install_writes_only_the_user_protocol_keys(tmp_path, monkeypatch):
    values = {}

    class Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        REG_SZ=1,
        CreateKey=lambda _root, path: Key(path),
        OpenKey=lambda _root, path: (_ for _ in ()).throw(FileNotFoundError(path)),
        SetValueEx=lambda key, name, _reserved, _kind, value: values.__setitem__(
            (key.path, name), value,
        ),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    result = web_entry.install_protocol(
        system="Windows",
        data_dir=tmp_path / "data",
        home=tmp_path,
        environment={"LOCALAPPDATA": str(tmp_path / "local")},
        python_executable=Path(r"C:\Python\pythonw.exe"),
    )

    assert result["status"] == "installed"
    assert (r"Software\Classes\mklink-ai-probe", "URL Protocol") in values
    assert values[(r"Software\Classes\mklink-ai-probe", "Mklink Web Entry Owner")]
    command_key = (r"Software\Classes\mklink-ai-probe\shell\open\command", "")
    assert '"%1"' in values[command_key]


def test_windows_uninstall_preserves_a_foreign_protocol_registration(tmp_path, monkeypatch):
    deleted = []

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_winreg = SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        OpenKey=lambda *_args: Key(),
        QueryValueEx=lambda _key, name: (
            ("another-product", 1)
            if name == "Mklink Web Entry Owner"
            else (str(tmp_path / "data" / "handler.py"), 1)
        ),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(
        web_entry,
        "_delete_windows_registry_tree",
        deleted.append,
    )

    result = web_entry.uninstall_protocol(
        system="Windows",
        data_dir=tmp_path / "data",
        home=tmp_path,
        environment={"LOCALAPPDATA": str(tmp_path / "local")},
    )

    assert result["status"] == "uninstalled"
    assert deleted == []
