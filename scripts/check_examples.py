#!/usr/bin/env python3
"""Check the examples without running them, and the docs regions inside them.

Examples start real tasks, so ``examples.yml`` runs them only by hand and on
release tags; nothing else proved they still compiled against the SDK. The
docs site also extracts snippets from ``# #region docs:<id>`` blocks in them
at a pinned release tag, so a broken example or a broken region ships a
broken docs page.

Two checks, both over every file without a list to keep up to date:

1. Every ``.py`` under ``examples/`` compiles, and every name it imports
   resolves: each imported module is found and each ``from m import name``
   names an attribute or submodule of ``m``. The example modules themselves
   are never imported, because some run their snippet at import time. Root
   ``ty check`` already type-checks ``examples/`` but ignores unresolved
   imports (``ty.toml``), which this covers.
2. Every ``# #region docs:<id>`` line in a tracked ``.py`` file is closed by a
   matching ``# #endregion docs:<id>`` in the same file, and no id appears
   twice in the repository.

Run it in the examples environment, so the examples' own dependencies
resolve:

    uv run --project examples python scripts/check_examples.py
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

MARKER = re.compile(r"^\s*# #(region|endregion) docs:(\S+)\s*$")
# A comment line that looks like a marker but does not match MARKER exactly.
LOOSE_MARKER = re.compile(r"^\s*#.*\b(end)?region\b.*\bdocs:")


def _module_found(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def _defined_names(module: str) -> set[str] | None:
    """Top-level names an example module defines, read from its source so
    the module never runs."""
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        return None
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return names


def _package_of(path: Path) -> str:
    # A module's package is its directory, and so is an __init__.py's.
    return ".".join(path.relative_to(EXAMPLES).parent.parts)


def _check_imports(path: Path, tree: ast.Module) -> list[str]:
    errors: list[str] = []
    where = path.relative_to(ROOT)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_found(alias.name):
                    errors.append(
                        f"{where}:{node.lineno}: cannot import {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = _package_of(path).split(".")
                base = package[: len(package) - (node.level - 1)]
                module = ".".join([*base, *filter(None, [node.module])])
            else:
                module = node.module or ""
            if module == "__future__":
                continue
            try:
                if module.split(".")[0] == "introspection_examples":
                    names = _defined_names(module)
                    if names is None:
                        raise ImportError(f"no module named {module!r}")
                else:
                    imported = importlib.import_module(module)
                    # hasattr, not dir(): a lazy module __getattr__ (the
                    # SDK's OTel names) is invisible to dir().
                    names = {
                        alias.name
                        for alias in node.names
                        if hasattr(imported, alias.name)
                    }
            except ImportError as exc:
                errors.append(
                    f"{where}:{node.lineno}: cannot import {module}: {exc}"
                )
                continue
            for alias in node.names:
                if alias.name == "*" or alias.name in names:
                    continue
                if not _module_found(f"{module}.{alias.name}"):
                    errors.append(
                        f"{where}:{node.lineno}: cannot import "
                        f"{alias.name} from {module}"
                    )
    return errors


def check_examples() -> list[str]:
    sys.path.insert(0, str(EXAMPLES))
    errors: list[str] = []
    for path in sorted(EXAMPLES.rglob("*.py")):
        if ".venv" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        try:
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
            continue
        errors.extend(_check_imports(path, ast.parse(source, str(path))))
    return errors


def check_regions() -> list[str]:
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "*.py",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    this_file = Path(__file__).resolve()
    errors: list[str] = []
    seen: dict[str, str] = {}
    for name in filter(None, tracked):
        path = ROOT / name
        if path.resolve() == this_file or not path.is_file():
            continue
        open_ids: dict[str, int] = {}
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            where = f"{name}:{lineno}"
            match = MARKER.match(line)
            if match is None:
                if LOOSE_MARKER.search(line):
                    errors.append(
                        f"{where}: malformed docs region marker; use "
                        "'# #region docs:<id>' / '# #endregion docs:<id>'"
                    )
                continue
            kind, region_id = match.groups()
            if kind == "region":
                if region_id in seen:
                    errors.append(
                        f"{where}: duplicate region id {region_id} "
                        f"(first at {seen[region_id]})"
                    )
                else:
                    seen[region_id] = where
                open_ids[region_id] = lineno
            elif region_id not in open_ids:
                errors.append(
                    f"{where}: endregion docs:{region_id} has no open region"
                )
            else:
                del open_ids[region_id]
        for region_id, lineno in open_ids.items():
            errors.append(
                f"{name}:{lineno}: region docs:{region_id} is never closed"
            )
    return errors


def main() -> int:
    errors = check_examples() + check_regions()
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f"{len(errors)} problem(s) found", file=sys.stderr)
        return 1
    print("examples compile, their imports resolve, docs regions are paired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
