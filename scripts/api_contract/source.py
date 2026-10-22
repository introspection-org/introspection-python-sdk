"""The SDK's source as parsed modules, with name lookup across them.

`introspection_sdk/_async/` is the source of truth for every class with a
sync twin, and `_sync/` is generated from it (see "Sync code generation" in
AGENTS.md), so `_sync/` is never read: it would count each call site twice.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

__all__ = ["Package", "Scope", "SourceModule"]

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

logger = logging.getLogger(__name__)


@dataclass
class SourceModule:
    name: str
    path: Path
    rel: str
    tree: ast.Module
    parents: dict[ast.AST, ast.AST] = field(default_factory=dict)

    @classmethod
    def parse(cls, name: str, path: Path, rel: str) -> SourceModule:
        tree = ast.parse(path.read_text(), filename=str(path))
        module = cls(name=name, path=path, rel=rel, tree=tree)
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                module.parents[child] = node
        return module

    @cached_property
    def functions(self) -> dict[str, FunctionNode]:
        return {
            n.name: n for n in self.tree.body if isinstance(n, FunctionNode)
        }

    @cached_property
    def constants(self) -> dict[str, ast.expr]:
        out: dict[str, ast.expr] = {}
        for n in self.tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1:
                target = n.targets[0]
                if isinstance(target, ast.Name):
                    out[target.id] = n.value
            elif isinstance(n, ast.AnnAssign) and n.value is not None:
                if isinstance(n.target, ast.Name):
                    out[n.target.id] = n.value
        return out

    @cached_property
    def imports(self) -> dict[str, tuple[str, str]]:
        """`local name -> (module, attribute)` for `from x import y`."""
        out: dict[str, tuple[str, str]] = {}
        for n in ast.walk(self.tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                for alias in n.names:
                    out[alias.asname or alias.name] = (n.module, alias.name)
        return out

    def line(self, node: ast.AST) -> str:
        return f"{self.rel}:{getattr(node, 'lineno', 0)}"

    def chain(self, node: ast.AST) -> list[FunctionNode]:
        """The functions enclosing `node`, innermost first."""
        out: list[FunctionNode] = []
        current = self.parents.get(node)
        while current is not None:
            if isinstance(current, FunctionNode):
                out.append(current)
            current = self.parents.get(current)
        return out


@dataclass
class Package:
    """Every module of the SDK, by dotted name."""

    root: Path
    modules: dict[str, SourceModule]

    @classmethod
    def load(cls, root: Path, package: str = "introspection_sdk") -> Package:
        modules: dict[str, SourceModule] = {}
        base = root / package
        for path in sorted(base.rglob("*.py")):
            parts = path.relative_to(root).with_suffix("").parts
            if "_sync" in parts:
                continue
            if parts[-1] == "__init__":
                parts = parts[:-1]
            name = ".".join(parts)
            rel = path.relative_to(root).as_posix()
            modules[name] = SourceModule.parse(name, path, rel)
        logger.debug(
            "SDK source parsed",
            extra={"package": package, "modules": len(modules)},
        )
        return cls(root=root, modules=modules)

    def resolve_import(
        self, module: SourceModule, name: str
    ) -> tuple[SourceModule, str] | None:
        """The module that defines `name` as seen from `module`."""
        seen: set[tuple[str, str]] = set()
        while (module.name, name) not in seen:
            seen.add((module.name, name))
            if name in module.functions or name in module.constants:
                return module, name
            target = module.imports.get(name)
            if target is None or target[0] not in self.modules:
                return None
            module, name = self.modules[target[0]], target[1]
        return None


@dataclass(frozen=True)
class Scope:
    """Where an expression is read: its module and enclosing functions."""

    package: Package
    module: SourceModule
    chain: tuple[FunctionNode, ...]

    @classmethod
    def of(
        cls, package: Package, module: SourceModule, node: ast.AST
    ) -> Scope:
        return cls(package, module, tuple(module.chain(node)))

    def inside(self, module: SourceModule, function: FunctionNode) -> Scope:
        return Scope(self.package, module, (function,))

    def is_parameter(self, name: str) -> bool:
        return any(
            arg.arg == name
            for function in self.chain
            for arg in [
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            ]
        )

    def assignment(self, name: str, before: int) -> ast.expr | None:
        """The last `name = ...` in the enclosing functions before a line."""
        for function in self.chain:
            best: tuple[int, ast.expr] | None = None
            for node in ast.walk(function):
                line = getattr(node, "lineno", None)
                if line is None or line >= before:
                    continue
                value = _assigned(node, name)
                if value is not None and (best is None or line > best[0]):
                    best = (line, value)
            if best is not None:
                return best[1]
        return None


def _assigned(node: ast.AST, name: str) -> ast.expr | None:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return node.value
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
    ):
        return node.value
    return None
