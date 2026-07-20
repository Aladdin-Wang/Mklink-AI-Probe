import importlib.util
import urllib.error
import urllib.parse
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "release"
    / "publish_update_release.py"
)


@pytest.fixture
def publisher():
    spec = importlib.util.spec_from_file_location("mklink_update_publisher", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_latest_document_matches_tauri_v2_schema(publisher):
    document = publisher.build_latest_document(
        version="0.1.0",
        notes="Stable release",
        published_at="2026-07-21T01:02:03Z",
        signature="signed-value",
        url="https://gitee.example/download.nsis.zip",
    )

    assert document == {
        "version": "0.1.0",
        "notes": "Stable release",
        "pub_date": "2026-07-21T01:02:03Z",
        "platforms": {
            "windows-x86_64": {
                "signature": "signed-value",
                "url": "https://gitee.example/download.nsis.zip",
            }
        },
    }


def test_gitee_request_uses_official_token_parameter_and_redacts_errors(
    publisher, monkeypatch,
):
    request = publisher.build_gitee_request(
        method="POST",
        path="/repos/owner/repo/releases",
        token="secret-token",
        payload={"tag_name": "v0.1.0"},
    )

    parsed = urllib.parse.urlsplit(request.full_url)
    assert parsed.path == "/api/v5/repos/owner/repo/releases"
    assert urllib.parse.parse_qs(parsed.query) == {"access_token": ["secret-token"]}
    assert b"secret-token" not in (request.data or b"")
    assert urllib.parse.parse_qs(request.data.decode()) == {"tag_name": ["v0.1.0"]}
    assert "secret-token" not in repr(request)

    def fail(_request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(publisher.urllib.request, "urlopen", fail)
    with pytest.raises(publisher.GiteeApiError) as captured:
        publisher.request_json(request)
    assert "secret-token" not in str(captured.value)


def test_resolve_gitee_token_uses_git_credential_without_echoing_secret(
    publisher, monkeypatch,
):
    calls = []

    class Result:
        returncode = 0
        stdout = "protocol=https\nhost=gitee.com\nusername=maintainer\npassword=credential-token\n"
        stderr = ""

    monkeypatch.delenv("GITEE_TOKEN", raising=False)
    monkeypatch.setattr(
        publisher.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Result(),
    )

    assert publisher.resolve_gitee_token() == "credential-token"
    assert calls[0][1]["input"] == "protocol=https\nhost=gitee.com\n\n"


def test_gitee_release_creation_is_idempotent(publisher, monkeypatch):
    calls = []
    existing = {"id": 42, "tag_name": "v0.1.0", "assets": []}

    def request_json(request):
        calls.append((request.method, request.full_url))
        if request.method == "GET":
            return existing
        raise AssertionError("existing release must not be recreated")

    monkeypatch.setattr(publisher, "request_json", request_json)

    result = publisher.ensure_gitee_release(
        owner="owner",
        repo="repo",
        token="token",
        tag="v0.1.0",
        title="Mklink AI Probe v0.1.0",
        notes="Stable release",
    )

    assert result == existing
    assert calls == [
        (
            "GET",
            "https://gitee.com/api/v5/repos/owner/repo/releases/tags/v0.1.0?access_token=token",
        )
    ]


def test_updates_branch_is_published_only_after_both_releases_and_verification(
    publisher, monkeypatch, tmp_path,
):
    events = []
    archive = tmp_path / "Mklink-AI-Probe-v0.1.0-x64.nsis.zip"
    signature = tmp_path / "Mklink-AI-Probe-v0.1.0-x64.nsis.zip.sig"
    archive.write_bytes(b"archive")
    signature.write_text("signature", encoding="ascii")

    monkeypatch.setattr(publisher, "push_version_tag", lambda **_kwargs: events.append("tag"))
    monkeypatch.setattr(publisher, "publish_github_release", lambda **_kwargs: events.append("github"))
    monkeypatch.setattr(
        publisher,
        "publish_gitee_release",
        lambda **_kwargs: events.append("gitee") or {
            "updater_url": "https://gitee.example/archive.nsis.zip"
        },
    )
    monkeypatch.setattr(
        publisher,
        "verify_public_asset",
        lambda **_kwargs: events.append("verify"),
    )
    monkeypatch.setattr(
        publisher,
        "publish_updates_branch",
        lambda **_kwargs: events.append("updates"),
    )

    publisher.publish_update_release(
        version="0.1.0",
        notes="Stable release",
        published_at="2026-07-21T01:02:03Z",
        release_dir=tmp_path,
        updater_archive=archive,
        updater_signature=signature,
        github_repo="Aladdin-Wang/Mklink-AI-Probe",
        gitee_repo="Aladdin-Wang/Mklink-AI-Probe",
        gitee_token="token",
        repository=tmp_path,
    )

    assert events == ["tag", "github", "gitee", "verify", "updates"]
