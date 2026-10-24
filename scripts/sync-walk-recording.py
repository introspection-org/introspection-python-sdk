"""Refresh the walk's recording from the JS SDK, the cross-SDK contract.

Every SDK's walk replays the same server responses: the HAR the JS walk
records against the Compose stack (introspection-cloud
``docs/design/sdk-end-to-end-walk.md``). This copies that HAR and its
``bootstrap.json`` into ``tests/recordings/walk/`` so the four SDKs stay in
lockstep::

    uv run python scripts/sync-walk-recording.py            # from GitHub main
    uv run python scripts/sync-walk-recording.py --ref <sha>
    uv run python scripts/sync-walk-recording.py --from ../introspection-js-sdk

From GitHub it takes a shallow, sparse clone through the caller's own git
credentials; ``--from`` reads a local checkout instead. Polly names the
recording directory ``walk_<hash>``; whichever ``walk_*`` holds a
``recording.har`` is the one taken.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "introspection-org/introspection-js-sdk"
RECORDINGS = "tests/recordings"
TARGET = Path(__file__).resolve().parent.parent / "tests/recordings/walk"


def _from_github(ref: str) -> tuple[bytes, bytes]:
    # A shallow, sparse clone: only the recordings, through the caller's own
    # git credentials, so a private checkout works too.
    with tempfile.TemporaryDirectory() as tmp:
        git = ["git", "-C", tmp]
        subprocess.run(["git", "init", "-q", tmp], check=True)
        subprocess.run(
            [*git, "remote", "add", "origin", f"https://github.com/{REPO}"],
            check=True,
        )
        subprocess.run(
            [
                *git,
                "sparse-checkout",
                "set",
                "--no-cone",
                f"/{RECORDINGS}/walk*",
            ],
            check=True,
        )
        subprocess.run(
            [
                *git,
                "fetch",
                "-q",
                "--depth",
                "1",
                "--filter=blob:none",
                "origin",
                ref,
            ],
            check=True,
        )
        subprocess.run([*git, "checkout", "-q", "FETCH_HEAD"], check=True)
        return _from_checkout(Path(tmp))


def _from_checkout(root: Path) -> tuple[bytes, bytes]:
    recordings = root / RECORDINGS
    hars = sorted(recordings.glob("walk_*/recording.har"))
    if not hars:
        sys.exit(f"{recordings} has no walk_*/recording.har")
    bootstrap = recordings / "walk" / "bootstrap.json"
    return hars[-1].read_bytes(), bootstrap.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0]
    )
    parser.add_argument("--ref", default="main", help="git ref on GitHub")
    parser.add_argument(
        "--from",
        dest="checkout",
        type=Path,
        help="a local introspection-js-sdk checkout instead of GitHub",
    )
    args = parser.parse_args()
    har, bootstrap = (
        _from_checkout(args.checkout)
        if args.checkout
        else _from_github(args.ref)
    )
    entries = json.loads(har)["log"]["entries"]
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / "recording.har").write_bytes(har)
    (TARGET / "bootstrap.json").write_bytes(bootstrap)
    print(f"tests/recordings/walk: {len(entries)} entries")


if __name__ == "__main__":
    main()
