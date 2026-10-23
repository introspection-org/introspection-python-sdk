#!/usr/bin/env python3
"""Check this SDK against the `x-introspection` flags of both API references.

The references are the Control Plane and Data Plane OpenAPI documents each
plane serves at `/openapi.json`, which introspection-cloud writes from its
API surface file: an operation is for every client unless its
`x-introspection` names the clients expected to call it, and this SDK is
the `sdk` client. See `scripts/api_contract/check.py` for what fails, with
and without `--pr`.

There is no list here of the operations this SDK covers, skips or exempts:
the cloud flags are the only classification, so a route the cloud adds for
the SDK fails the full check until the SDK calls it.

`.github/workflows/api-contract.yml` runs it with `--pr` on pull requests,
and in full with `--notify` after each staging deploy. `--notify DIR` tells
#main-build-alerts when the state changes (clean to drift, drift to clean),
the way introspection-cloud's main-status.yml does: a `{text}` JSON posted to
`SLACK_WEBHOOK_URL`, printed instead when that is empty. DIR keeps the state
of the last real post between runs, so a drift that stays drift stays quiet.

Any failure to read a reference (an HTTP error status, a network error,
a body that is not JSON, or `STAGING_DP_URL` unset) exits 2 before the
check runs: it posts nothing and leaves the posted state as it was.

Run: STAGING_DP_URL=https://api.<dp host> \
     uv run python scripts/check_api_contract.py [--pr] [--notify DIR]
         [--controlplane URL|PATH] [--dataplane URL|PATH]
env: STAGING_DP_URL, the staging Data Plane's base URL, required unless
     the Data Plane is named otherwise; API_CONTRACT_CONTROLPLANE,
     API_CONTRACT_DATAPLANE replace a staging document with a URL or a
     file, as the flags do; SLACK_WEBHOOK_URL as above.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

from api_contract.check import Result, run
from api_contract.reference import load_reference, reference_source
from api_contract.source import Package

ROOT = Path(__file__).resolve().parent.parent
PLANES = ("controlplane", "dataplane")
HEADLINES = {
    "drift": "🚨 API drift: introspection-python-sdk is out of step with the "
    "staging API references",
    "clean": "✅ API drift cleared: introspection-python-sdk matches the "
    "staging API references again",
}
#: Characters the drift may take in the Slack message: one much past this is
#: unreadable in the channel, and the job summary has the rest.
DRIFT_BUDGET = 3500

logger = logging.getLogger(__name__)


def trim(text: str, budget: int) -> str:
    """The first lines of `text` that fit in `budget` characters."""
    if len(text) <= budget:
        return text
    kept: list[str] = []
    used = 0
    lines = text.split("\n")
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    rest = len(lines) - len(kept)
    return "\n".join(kept) + f"\n… {rest} more lines, in the job summary"


def slack_escape(text: str) -> str:
    """Slack reads & < > as control characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notify(result: Result, state_dir: Path, run_url: str) -> bool:
    """Posts on a state change; True when a post was made."""
    state = "drift" if result.failed() else "clean"
    last = state_dir / "last-posted"
    previous = last.read_text().strip() if last.exists() else ""
    print(f"state={state} last posted={previous or 'none'}")
    if state == previous or (state == "clean" and previous != "drift"):
        print("No state change; staying quiet.")
        return False
    message = f"{HEADLINES[state]}\n{run_url}"
    if state == "drift":
        drift = trim(result.render(), DRIFT_BUDGET)
        message += f"\n```\n{slack_escape(drift)}\n```"
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        print(f"Slack post withheld (no webhook), would have sent:\n{message}")
        return False
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"text": message}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20):
        pass
    logger.info("API drift posted", extra={"state": state})
    print("Posted to Slack.")
    state_dir.mkdir(parents=True, exist_ok=True)
    last.write_text(f"{state}\n")
    return True


def _load(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    """Both references; raises when either cannot be read."""
    return {
        plane: load_reference(reference_source(plane, getattr(args, plane)))
        for plane in PLANES
    }


def _write(path: str | None, text: str) -> None:
    if path:
        with open(path, "a") as out:
            out.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check this SDK against the API references."
    )
    for plane in PLANES:
        parser.add_argument(f"--{plane}", metavar="URL|PATH")
    parser.add_argument(
        "--pr",
        action="store_true",
        help="fail only on routes in neither reference",
    )
    parser.add_argument("--notify", metavar="STATE_DIR", type=Path)
    parser.add_argument("--run-url", default="(local run)")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    try:
        specs = _load(args)
        result = run(Package.load(ROOT), specs)
        full = not args.pr
        text = result.render(full=full)
        print(text)
        _write(summary, f"## API contract\n\n```\n{text}\n```\n")
        if args.notify is not None:
            posted = notify(result, args.notify, args.run_url)
            _write(
                os.environ.get("GITHUB_OUTPUT"),
                f"posted={str(posted).lower()}\n",
            )
    except Exception as exc:
        logger.exception("could not run the API contract check")
        print(f"::error::could not run the API contract check: {exc}")
        return 2
    return 1 if result.failed(full=full) else 0


if __name__ == "__main__":
    sys.exit(main())
