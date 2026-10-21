#!/usr/bin/env python3
"""Check the public API against the latest release for breaking changes.

Wraps ``griffe check``: it loads ``introspection_sdk`` from the working tree
and from a release tag, and reports every change that can break a caller —
a public object removed or renamed, a parameter removed, reordered, made
required or changed kind, a return or attribute type changed, a base class
dropped.

What counts as public is griffe's rule: a module's ``__all__`` when it has
one; otherwise every name that does not start with an underscore. Names
imported into a module are public only through ``__all__``. ``_``-prefixed
modules and packages (``_http``, ``_errors``, ``otel/_provider``, ...) and
everything in them are internal.

One griffe breakage kind is dropped: "attribute value was changed". Here the
value of a public attribute is almost always a pydantic ``Field(...)`` whose
description was edited, a type alias whose union gained a member, or a string
built from the version, and none of those breaks a caller. A changed type
annotation on the same attribute is still reported.

The tag defaults to the latest ``v*`` release reachable from ``HEAD``, which
needs the tags and the history (``fetch-depth: 0`` in CI):

    uv run python scripts/check_api.py
    uv run python scripts/check_api.py --against v0.29.0
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import griffe

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "introspection_sdk"

IGNORED = {griffe.BreakageKind.ATTRIBUTE_CHANGED_VALUE}


def _latest_release() -> str:
    return subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the public API against a release."
    )
    parser.add_argument(
        "--against",
        help="git ref to compare with (default: the latest v* tag)",
    )
    args = parser.parse_args()
    against = args.against or _latest_release()

    old = griffe.load_git(PACKAGE, ref=against, repo=ROOT)
    new = griffe.load(PACKAGE, search_paths=[ROOT])

    breakages = [
        b
        for b in griffe.find_breaking_changes(old, new)
        if b.kind not in IGNORED
    ]
    for breakage in breakages:
        print(breakage.explain(), file=sys.stderr)

    if breakages:
        print(
            f"\n{len(breakages)} breaking change(s) to the public API "
            f"against {against}. See 'Public API compatibility' in "
            "AGENTS.md to break it on purpose.",
            file=sys.stderr,
        )
        return 1
    print(f"No breaking changes to the public API against {against}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
