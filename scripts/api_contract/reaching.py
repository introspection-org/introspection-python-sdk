"""Which values of a local name reach a point of a function body.

A later assignment replaces an earlier one, each branch of an `if` or case
of a `match` keeps its own, a loop body and its `else` see what earlier
passes assigned, and an `except` handler sees every value its `try` body
assigned. A block that leaves by `return`, `raise`, `break` or `continue`
passes nothing on to the statement after it; a `break` or `continue` passes
its values to where it jumps.

Points are `(line, column)` positions, so two statements on one line keep
their order.
"""

from __future__ import annotations

import ast
import sys

__all__ = ["END", "Position", "position", "reaching"]

Position = tuple[int, int]

#: A position past every statement, to read the values that leave a block.
END: Position = (sys.maxsize, 0)

#: Statements after which the rest of their block does not run.
JUMPS = ast.Return | ast.Raise | ast.Break | ast.Continue
#: Nodes whose assignments are another scope's.
NESTED_SCOPES = (
    ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda
)


def position(node: ast.stmt | ast.expr) -> Position:
    return (node.lineno, node.col_offset)


def reaching(
    body: list[ast.stmt],
    name: str,
    before: Position,
    *,
    incoming: ast.expr | None = None,
) -> list[ast.expr]:
    """Every value reaching `before`, including an optional entry value."""
    return _reaching(
        body, name, before, [incoming] if incoming is not None else []
    )


def _end(node: ast.stmt) -> Position:
    return (node.end_lineno or node.lineno, node.end_col_offset or 0)


def _reaching(
    body: list[ast.stmt], name: str, before: Position, values: list[ast.expr]
) -> list[ast.expr]:
    """The values of `name` that reach `before` through `body`, when
    `values` reach the start of it."""
    for stmt in body:
        if position(stmt) >= before:
            break
        values, inside = _through(stmt, name, before, values)
        if inside:
            return values
        if not _completes([stmt]):
            return []
    return values


def _through(
    stmt: ast.stmt, name: str, before: Position, values: list[ast.expr]
) -> tuple[list[ast.expr], bool]:
    """The values of `name` at `before` and True when it is in `stmt`, else
    the values that leave it and False."""
    if isinstance(stmt, ast.Try | ast.TryStar):
        return _through_try(stmt, name, before, values)
    if isinstance(stmt, ast.For | ast.AsyncFor | ast.While):
        return _through_loop(stmt, name, before, values)
    branches = _branches(stmt)
    held = [b for b in branches if _holds(b, before)]
    if held:
        return _reaching(held[0], name, before, values), True
    if _end(stmt) > before:
        # The point is in the statement's own expressions, a test or a
        # pattern, which run before any of its blocks.
        return values, True
    value = _assigned(stmt, name)
    if value is not None:
        return [value], False
    if isinstance(stmt, ast.With | ast.AsyncWith):
        # A context manager may suppress a raised exception. Preserve the
        # values at the raise, not assignments after that exit.
        suppressed = [
            v
            for point in _raises(stmt.body)
            for v in _reaching(stmt.body, name, point, values)
        ]
        normal = (
            _reaching(stmt.body, name, END, values)
            if _completes(stmt.body)
            else []
        )
        return _union([*normal, *suppressed]), False
    if not branches:
        return values, False
    reached = [
        v
        for b in branches
        if _completes(b)
        for v in _reaching(b, name, END, values)
    ]
    return _union(reached), False


def _through_loop(
    stmt: ast.For | ast.AsyncFor | ast.While,
    name: str,
    before: Position,
    values: list[ast.expr],
) -> tuple[list[ast.expr], bool]:
    """Like `_through`, for a loop. Each pass of the body starts with the
    values from before the loop or from the end of an earlier pass or its
    `continue`; `else` runs after the last pass, or none, and `break`
    leaves past it."""

    def at(points: list[Position], entry: list[ast.expr]) -> list[ast.expr]:
        return [
            v for p in points for v in _reaching(stmt.body, name, p, entry)
        ]

    ended = _reaching(stmt.body, name, END, values)
    again = [
        *(ended if _completes(stmt.body) else []),
        *at(_jumps(stmt.body, ast.Continue), values),
    ]
    top = _union([*values, *again])
    if _holds(stmt.body, before):
        return _reaching(stmt.body, name, before, top), True
    completed = _reaching(stmt.orelse, name, before, top)
    if _holds(stmt.orelse, before):
        return completed, True
    if before < position(stmt.body[0]):
        return top, True
    broken = at(_jumps(stmt.body, ast.Break), top)
    if not _completes(stmt.orelse):
        completed = []
    return _union([*completed, *broken]), False


def _jumps(body: list[ast.stmt], kind: type[ast.stmt]) -> list[Position]:
    """The positions of the `break` or `continue` statements in `body` that
    act on the loop whose body it is."""
    out: list[Position] = []
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, kind):
            out.append(position(node))
        elif isinstance(node, ast.For | ast.AsyncFor | ast.While):
            # A nested loop's own body jumps in that loop.
            pending.extend(node.orelse)
        elif not isinstance(node, NESTED_SCOPES):
            pending.extend(ast.iter_child_nodes(node))
    return out


def _through_try(
    stmt: ast.Try | ast.TryStar,
    name: str,
    before: Position,
    values: list[ast.expr],
) -> tuple[list[ast.expr], bool]:
    """Like `_through`, for a `try`. A handler is entered from any point of
    the body, and `finally` from any point of the rest."""
    raised = _union([*values, *_assigned_anywhere(stmt.body, name)])
    body = _reaching(stmt.body, name, before, values)
    if _holds(stmt.body, before):
        return body, True
    orelse = _reaching(stmt.orelse, name, before, body)
    if _holds(stmt.orelse, before):
        return orelse, True
    completed = [orelse] if _completes([*stmt.body, *stmt.orelse]) else []
    for handler in stmt.handlers:
        handled = _reaching(handler.body, name, before, raised)
        if _holds(handler.body, before):
            return handled, True
        if _completes(handler.body):
            completed.append(handled)
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
    # An empty value set can still belong to a completing path whose first
    # assignment is in finally. Keep completion separate from those values.
    if not completed or not _completes(stmt.finalbody):
        return [], False
    return _reaching(stmt.finalbody, name, before, normal), False


def _completes(body: list[ast.stmt]) -> bool:
    """Whether running `body` can reach its end, rather than leave by a
    `return`, `raise`, `break` or `continue` in every branch."""
    for stmt in body:
        if isinstance(stmt, JUMPS):
            return False
        if isinstance(stmt, ast.Try | ast.TryStar):
            if not _try_completes(stmt):
                return False
            continue
        if isinstance(stmt, ast.With | ast.AsyncWith) and _raises(stmt.body):
            continue
        branches = _branches(stmt)
        if branches and not any(map(_completes, branches)):
            return False
    return True


def _try_completes(stmt: ast.Try | ast.TryStar) -> bool:
    """Finally preserves a pending exit unless it exits itself."""
    normal = _completes(stmt.body) and _completes(stmt.orelse)
    handled = any(_completes(handler.body) for handler in stmt.handlers)
    return (normal or handled) and _completes(stmt.finalbody)


def _raises(body: list[ast.stmt]) -> list[Position]:
    """Explicit exception exits a context manager may suppress."""
    out: list[Position] = []
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Raise):
            out.append(position(node))
        elif not isinstance(node, NESTED_SCOPES):
            pending.extend(ast.iter_child_nodes(node))
    return out


def _holds(body: list[ast.stmt], point: Position) -> bool:
    return bool(body) and position(body[0]) <= point < _end(body[-1])


def _union(values: list[ast.expr]) -> list[ast.expr]:
    return list({id(v): v for v in values}.values())


def _assigned_anywhere(body: list[ast.stmt], name: str) -> list[ast.expr]:
    """Every value `body` assigns to `name` at any depth, in source order,
    outside the functions and classes it defines."""
    out: list[ast.expr] = []
    pending: list[ast.AST] = list(body)
    while pending:
        node = pending.pop()
        if isinstance(node, NESTED_SCOPES):
            continue
        value = _assigned(node, name)
        if value is not None:
            out.append(value)
        pending.extend(ast.iter_child_nodes(node))
    return sorted(out, key=lambda v: (v.lineno, v.col_offset))


def _branches(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """The blocks a compound statement other than a loop or `try` may run,
    in source order; an empty one stands for running none of them."""
    if isinstance(stmt, ast.If):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, ast.With | ast.AsyncWith):
        return [stmt.body]
    if isinstance(stmt, ast.Match):
        cases = [case.body for case in stmt.cases]
        return cases if any(map(_catches_all, stmt.cases)) else [*cases, []]
    return []


def _catches_all(case: ast.match_case) -> bool:
    return (
        case.guard is None
        and isinstance(case.pattern, ast.MatchAs)
        and case.pattern.pattern is None
    )


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
