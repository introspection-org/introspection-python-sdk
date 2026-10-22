#!/usr/bin/env python3
"""Build the nightly API drift report that `.github/workflows/api-contract.yml`
posts to #main-build-alerts.

Two reports, because they answer different questions:

- The SDK drift: where this SDK's routes disagree with the staging
  references' `x-introspection` flags, from `scripts/check_api_contract.py`.
- The reference changelog: what changed in the staging API since the saved
  copies in `api-reference/` were taken, from oasdiff.

Either one being non-empty is drift: SDK drift needs fixing, and a changelog
means the saved copies are behind even when the SDK happens to match.

The report is written to --out as files the notify step reads:

  state        drift | clean
  body.txt     the Slack message below its headline: summary, run link, and
               the drift itself (SDK drift, changed planes) trimmed to fit
  summary.md   both reports in full, for the job summary

Exits 0 when the report was built (drift or clean) and 2 when it could not
be, for example when staging did not answer: an outage is not drift, and
must not post or change the notify state. A reference that answers 404 has
not been published on staging yet: that run exits 0 and writes no report,
so the workflow skips the notify step and records no state.

Run: uv run python scripts/api_drift_report.py --out DIR [--run-url URL]
env: OASDIFF (default: oasdiff on PATH), and the reference overrides
     check_api_contract.py reads.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import urllib.error
from pathlib import Path

from api_contract.changelog import changelog, render_plane
from api_contract.check import run
from api_contract.reference import load_reference, reference_source
from api_contract.source import Package

ROOT = Path(__file__).resolve().parent.parent
PLANES = ("controlplane", "dataplane")

#: Characters the SDK drift, and each plane's changelog, may take in the
#: Slack message. Slack cuts a message at 40,000 characters, but one much
#: past 10,000 is unreadable in the channel; the job summary has the rest.
DRIFT_BUDGET = 3500
PLANE_BUDGET = 2500

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


def build(out: Path, run_url: str, overrides: dict[str, str | None]) -> bool:
    """Writes the report; True when there is drift."""
    specs = {
        plane: load_reference(reference_source(plane, overrides.get(plane)))
        for plane in PLANES
    }
    planes = []
    with tempfile.TemporaryDirectory() as tmp:
        for plane in PLANES:
            # oasdiff reads the same bytes the check read.
            live = Path(tmp) / f"{plane}.json"
            live.write_text(json.dumps(specs[plane]))
            saved = ROOT / "api-reference" / f"{plane}.json"
            planes.append(
                render_plane(plane, changelog(str(saved), str(live)))
            )
    result = run(Package.load(ROOT), specs)
    drifted = result.failed or any(p.changed for p in planes)
    summary_lines = [
        f"SDK drift: {result.counts() if result.failed else 'none'}",
        *(f"Reference {p.header}" for p in planes),
    ]
    blocks = [trim(result.render(), DRIFT_BUDGET)] if result.failed else []
    blocks += [trim(p.text, PLANE_BUDGET) for p in planes if p.changed]
    body = "\n".join([*summary_lines, run_url]) + "".join(
        f"\n```\n{block}\n```" for block in blocks
    )
    if not drifted:
        body = run_url
    out.mkdir(parents=True, exist_ok=True)
    (out / "state").write_text("drift\n" if drifted else "clean\n")
    (out / "body.txt").write_text(slack_escape(body) + "\n")
    (out / "summary.md").write_text(
        f"## API drift: {'drift' if drifted else 'clean'}\n\n"
        + "".join(f"- {line}\n" for line in summary_lines)
        + f"\n### SDK drift\n\n```\n{result.render()}\n```\n"
        + "\n### Reference changelog\n\n```\n"
        + "\n\n".join(p.text for p in planes)
        + "\n```\n"
    )
    logger.info(
        "API drift report built",
        extra={"state": "drift" if drifted else "clean"},
    )
    print(f"API drift: {'drift' if drifted else 'clean'}")
    print("\n".join(summary_lines))
    return drifted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the nightly API drift report."
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--run-url", default="(local run)")
    for plane in PLANES:
        parser.add_argument(f"--{plane}", metavar="URL|PATH")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        build(
            args.out,
            args.run_url,
            {plane: getattr(args, plane) for plane in PLANES},
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return _failed(exc)
        logger.info("API reference not published", extra={"url": exc.url})
        print("reference not published on staging yet, skipping")
        return 0
    except Exception as exc:
        return _failed(exc)
    return 0


def _failed(exc: Exception) -> int:
    logger.exception("could not build the API drift report")
    print(f"::error::could not build the API drift report: {exc}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
