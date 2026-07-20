import subprocess
import sys
from pathlib import Path

import pytest


def test_top_level_help_renders_systemview_commands():
    root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        [sys.executable, "-m", "mklink", "--help"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "systemview-analyze" in result.stdout


@pytest.mark.parametrize(
    "command",
    ["symbols", "hardfault", "typeinfo", "memmap", "watch", "superwatch", "vofa", "break"],
)
def test_elf_commands_expose_explicit_backend_choice(command):
    root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        [sys.executable, "-m", "mklink", command, "--help"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "--elf-backend {builtin,external}" in result.stdout
