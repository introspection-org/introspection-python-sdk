"""The reference changelog: what changed in the staging API since the saved
copies in `api-reference/` were taken, from oasdiff."""

from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

__all__ = ["PlaneChanges", "changelog", "render_plane"]

#: oasdiff's levels: 3 is breaking, 2 potentially breaking.
LEVELS = {3: "BREAKING: ", 2: "MAYBE BREAKING: "}


def changelog(saved: str, live: str) -> list[dict[str, Any]]:
    """oasdiff's JSON changelog from the saved copy to the live document.
    `OASDIFF` names the binary (default: `oasdiff` on PATH)."""
    binary = os.environ.get("OASDIFF", "oasdiff")
    try:
        done = subprocess.run(
            [binary, "changelog", saved, live, "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"could not run {binary}: {exc}") from exc
    if done.returncode != 0:
        raise RuntimeError(
            f"oasdiff could not compare {saved} with {live}: "
            f"{done.stderr.strip()}"
        )
    return json.loads(done.stdout or "[]")


def _where(change: dict[str, Any]) -> str:
    if change.get("path"):
        return f"{change.get('operation', '')} {change['path']}".strip()
    return str(change.get("section", ""))


@dataclass(frozen=True)
class PlaneChanges:
    header: str
    text: str
    changed: bool


def render_plane(plane: str, changes: list[dict[str, Any]]) -> PlaneChanges:
    """One plane's changes, most important first: operations added and
    removed, then one line per distinct change with every operation it
    applies to, because a parameter added to forty endpoints is one fact."""
    added = sorted(_where(c) for c in changes if c["id"] == "endpoint-added")
    removed = sorted(
        _where(c) for c in changes if c["id"] == "endpoint-removed"
    )
    grouped: dict[tuple[int, str], list[str]] = defaultdict(list)
    for c in changes:
        if c["id"] not in ("endpoint-added", "endpoint-removed"):
            grouped[(c.get("level", 1), c.get("text", c["id"]))].append(
                _where(c)
            )
    lines = [
        f"  {LEVELS.get(level, '')}{text} — {', '.join(sorted(set(where)))}"
        for (level, text), where in sorted(
            grouped.items(), key=lambda item: (-item[0][0], -len(item[1]))
        )
    ]
    count = defaultdict(int)
    for c in changes:
        count[c.get("level", 1)] += 1
    header = (
        f"{plane}: {len(changes)} changes — {count[3]} breaking, "
        f"{count[2]} potentially breaking, {len(added)} operations added, "
        f"{len(removed)} removed"
    )
    body = [header]
    if added:
        body.append(f"  operations added: {', '.join(added)}")
    if removed:
        body.append(f"  BREAKING: operations removed: {', '.join(removed)}")
    return PlaneChanges(header, "\n".join(body + lines), bool(changes))
