"""Inventory public entry points without importing code or touching hardware.

This is a review aid, not proof of test coverage. Dynamic registrations require
manual review. Run from any directory; output paths are explicit.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    entries = []
    for path in sorted((ROOT / "mklink").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        relative = path.relative_to(ROOT).as_posix()
        if path.name == "shared_device.py":
            for cls in tree.body:
                if isinstance(cls, ast.ClassDef) and not cls.name.startswith("_"):
                    for method in cls.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and not method.name.startswith("_"):
                            entries.append(dict(kind="shared_sdk", name=cls.name + "." + method.name,
                                                source=relative, line=method.lineno))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                        continue
                    method = decorator.func.attr
                    if method == "tool":
                        entries.append(dict(kind="mcp", name=node.name, source=relative, line=node.lineno))
                    elif method in {"get", "post", "put", "delete", "patch", "websocket"}:
                        if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                            entries.append(dict(kind="route", name=method.upper() + " " + decorator.args[0].value,
                                                source=relative, line=node.lineno))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_parser":
                if node.args and isinstance(node.args[0], ast.Constant):
                    entries.append(dict(kind="cli", name=node.args[0].value, source=relative, line=node.lineno))
        if path.name == "capabilities.py":
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Capability":
                    if len(node.args) >= 3 and isinstance(node.args[2], ast.Tuple):
                        for operation in node.args[2].elts:
                            if isinstance(operation, ast.Constant):
                                entries.append(dict(kind="remote_operation", name=operation.value, source=relative, line=node.lineno))
    tests = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "_maintainer/testing/tests").glob("test_*.py"))]
    gui_tests = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "gui/src").rglob("*.test.ts"))]
    return {"scope": "Static registrations and declared shared SDK methods only; not coverage or execution evidence. Inherited methods and dynamic registrations need manual audit.",
            "entries": sorted(entries, key=lambda e: (e["kind"], e["source"], e["line"])),
            "python_test_files": tests, "gui_test_files": gui_tests}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": len(result["entries"]), "python_test_files": len(result["python_test_files"]),
                      "gui_test_files": len(result["gui_test_files"])}))
