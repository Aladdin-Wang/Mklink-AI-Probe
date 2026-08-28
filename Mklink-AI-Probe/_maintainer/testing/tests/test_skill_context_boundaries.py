import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import pytest

from _maintainer.release.prepare_release import (
    PUBLIC_SKILL_DIRECTORIES,
    _is_public_skill_file,
)


ROOT = Path(__file__).resolve().parents[3]
MAINTAINER_SKILLS = (
    ROOT / "skills" / "maintaining-mklink-ai-probe",
    ROOT / "skills" / "tauri-gui-builder",
)


def _frontmatter(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    _empty, header, _body = text.split("---", 2)
    return {line.strip() for line in header.splitlines() if line.strip()}


def test_maintainer_skills_are_explicit_only_in_codex():
    for skill in MAINTAINER_SKILLS:
        frontmatter = _frontmatter(skill / "SKILL.md")
        openai = (skill / "agents" / "openai.yaml").read_text(encoding="utf-8")

        assert any(line.startswith("description: Maintainer-only") for line in frontmatter)
        assert "allow_implicit_invocation: false" in openai


def test_end_user_skill_remains_implicitly_available():
    openai = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "allow_implicit_invocation: true" in openai


def test_user_entry_keeps_a_small_context_budget():
    # Character budgets guard progressive disclosure, not model token estimates.
    _empty, header, body = (ROOT / "SKILL.md").read_text(encoding="utf-8").split("---", 2)
    assert len(header) <= 350
    assert len(body) <= 4500


USER_DOCUMENTS = (ROOT / "SKILL.md", ROOT / "README.md", *sorted((ROOT / "references").glob("*.md")))


@pytest.mark.parametrize("document", USER_DOCUMENTS, ids=lambda path: path.name)
def test_user_document_links_stay_in_the_public_package(document):
    # Check every reference, including those reached only via another reference.
    for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (document.parent / unquote(parsed.path)).resolve()
        relative = PurePosixPath(target.relative_to(ROOT.resolve()).as_posix())
        assert target.exists(), f"{document.name}: missing {link}"
        assert _is_public_skill_file(relative) or relative in PUBLIC_SKILL_DIRECTORIES, (
            f"{document.name}: user documentation links to non-user content: {link}"
        )


@pytest.mark.parametrize("document", USER_DOCUMENTS, ids=lambda path: path.name)
def test_user_documents_do_not_invoke_repository_maintenance(document):
    text = document.read_text(encoding="utf-8")
    # Target firmware builds are legitimate user tasks; MKLink product maintenance is not.
    forbidden = re.compile(
        r"\bpytest\b|\bnpx\s+tauri\s+(?:dev|build)\b|\bpyinstaller\b"
        r"|\bnpm\s+(?:ci|install|run\s+(?:build|dev|test))\b"
        r"|(?:scripts[/\\])?(?:ai_memory\.py|build_workspace\.ps1)"
        r"|_maintainer[/\\]|docs/ai/|skills/(?:maintaining-mklink|tauri-gui-builder)",
        re.IGNORECASE,
    )
    assert not forbidden.search(text), f"{document.name}: maintenance instruction in user context"
