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

    def assignments(self, name: str, before: int) -> list[ast.expr]:
        """Every value `name = ...` can leave in `name` on a line, read in
        the innermost enclosing function that assigns it: a later
        assignment replaces an earlier one, each branch of an `if` keeps
        its own, and an `except` handler sees every value its `try` body
        assigned."""
        for function in self.chain:
            values = _reaching(function.body, name, before, [])
            if values:
                return values
        return []


def _reaching(
    body: list[ast.stmt], name: str, before: int, values: list[ast.expr]
) -> list[ast.expr]:
    """The values of `name` that reach line `before` through `body`, when
    `values` reach the start of it."""
    for stmt in body:
        if stmt.lineno >= before:
            break
        value = _assigned(stmt, name)
        if value is not None:
            values = [value]
            continue
        if isinstance(stmt, ast.Try | ast.TryStar):
            values, inside = _through_try(stmt, name, before, values)
            if inside:
                return values
            continue
        branches = _branches(stmt)
        if (stmt.end_lineno or stmt.lineno) >= before:
            # The line is inside this statement: follow the branch it is in.
            inside = [b for b in branches if b and b[0].lineno <= before]
            return (
                _reaching(inside[-1], name, before, values)
                if inside
                else values
            )
        if branches:
            reached = [
                v for b in branches for v in _reaching(b, name, before, values)
            ]
            values = _union(reached)
    return values


def _through_try(
    stmt: ast.Try | ast.TryStar,
    name: str,
    before: int,
    values: list[ast.expr],
) -> tuple[list[ast.expr], bool]:
    """The values of `name` at line `before` and True when the line is in
    `stmt`, else the values that leave it and False. A handler is entered
    from any point of the body, and `finally` from any point of the rest."""
    raised = _union([*values, *_assigned_anywhere(stmt.body, name)])
    body = _reaching(stmt.body, name, before, values)
    if _holds(stmt.body, before):
        return body, True
    completed = [_reaching(stmt.orelse, name, before, body)]
    if _holds(stmt.orelse, before):
        return completed[0], True
    for handler in stmt.handlers:
        completed.append(_reaching(handler.body, name, before, raised))
        if _holds(handler.body, before):
            return completed[-1], True
    normal = _union([v for c in completed for v in c])
    if _holds(stmt.finalbody, before):
        aborted = [
            *raised,
            *_assigned_anywhere(stmt.orelse, name),
            *(
                v
                for handler in stmt.handlers
                for v in _assigned_anywhere(handler.body, name)
            ),
        ]
        entry = _union([*normal, *aborted])
        return _reaching(stmt.finalbody, name, before, entry), True
    return _reaching(stmt.finalbody, name, before, normal), False


def _holds(body: list[ast.stmt], line: int) -> bool:
    return bool(body) and body[0].lineno <= line <= (
        body[-1].end_lineno or body[-1].lineno
    )


def _union(values: list[ast.expr]) -> list[ast.expr]:
    return list({id(v): v for v in values}.values())


def _assigned_anywhere(body: list[ast.stmt], name: str) -> list[ast.expr]:
    """Every value `body` assigns to `name` at any depth, in source order,
    outside the functions and classes it defines."""
    out: list[ast.expr] = []
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, FunctionNode | ast.ClassDef | ast.Lambda):
            continue
        value = _assigned(node, name)
        if value is not None:
            out.append(value)
        pending.extend(ast.iter_child_nodes(node))
    return sorted(out, key=lambda v: (v.lineno, v.col_offset))


def _branches(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """The blocks a compound statement may run, in source order; an empty
    one stands for running none of them."""
    if isinstance(stmt, ast.If):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, ast.For | ast.AsyncFor | ast.While):
        return [[], stmt.body, stmt.orelse]
    if isinstance(stmt, ast.With | ast.AsyncWith):
        return [stmt.body]
    return []


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
