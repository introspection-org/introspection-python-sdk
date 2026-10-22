#!/usr/bin/env python3
"""Build the nightly API drift report that `.github/workflows/api-contract.yml`
posts to #main-build-alerts.

Two reports, because they answer different questions:

- The SDK drift: where this SDK disagrees with the staging references'
  `x-introspection` flags and schemas, from `scripts/check_api_contract.py`.
- The reference changelog: what changed in the staging API since the saved
  copies in `api-reference/` were taken, from oasdiff.

Either one being non-empty is drift: SDK drift needs fixing, and a changelog
means the saved copies are behind even when the SDK happens to match.

The report is written to --out as files the notify step reads:

  state        drift | clean
  body.txt     the Slack message below its headline: summary, run link, and
               the agent prompt carrying both reports trimmed to fit
  summary.md   both reports in full, for the job summary

Exits 0 when the report was built (drift or clean) and 2 when it could not
be, for example when staging did not answer: an outage is not drift, and
must not post or change the notify state.

Run: uv run python scripts/api_drift_report.py --out DIR [--run-url URL]
env: OASDIFF (default: oasdiff on PATH), and the reference overrides
     check_api_contract.py reads.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from api_contract.changelog import changelog, render_plane
from api_contract.check import run
from api_contract.reference import load_reference, reference_source
from api_contract.report import render
from api_contract.source import Package

ROOT = Path(__file__).resolve().parent.parent
PLANES = ("controlplane", "dataplane")
PROMPT = ROOT / ".github" / "api-drift-prompt.md"

#: Characters the SDK drift, and each plane's changelog, may take in the
#: Slack message. Slack cuts a message at 40,000 characters, but one much
#: past 10,000 is unreadable in the channel; the job summary has the rest.
DRIFT_BUDGET = 3500
PLANE_BUDGET = 2500


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


def prompt(run_url: str, drift: str, changes: list[str]) -> str:
    text = re.sub(r"<!--.*?-->\s*", "", PROMPT.read_text(), flags=re.S)
    return (
        text.replace("{{RUN_URL}}", run_url)
        .replace("{{SDK_DRIFT}}", trim(drift, DRIFT_BUDGET))
        .replace(
            "{{CHANGELOG}}",
            "\n\n".join(trim(c, PLANE_BUDGET) for c in changes),
        )
        .strip()
    )


def build(out: Path, run_url: str, overrides: dict[str, str | None]) -> bool:
    """Writes the report; True when there is drift."""
    specs = {}
    planes = []
    with tempfile.TemporaryDirectory() as tmp:
        for plane in PLANES:
            source = reference_source(plane, overrides.get(plane))
            specs[plane] = load_reference(source)
            # oasdiff reads the same bytes the check read.
            live = Path(tmp) / f"{plane}.json"
            live.write_text(json.dumps(specs[plane]))
            saved = ROOT / "api-reference" / f"{plane}.json"
            planes.append(
                render_plane(plane, changelog(str(saved), str(live)))
            )
    result = run(Package.load(ROOT), specs)
    drift_text = render(result) if result.failed else "none"
    drifted = result.failed or any(p.changed for p in planes)
    counts = ", ".join(f"{n} {what}" for what, n in result.counts().items())
    summary_lines = [
        f"SDK drift: {counts if result.failed else 'none'}",
        *(f"Reference {p.header}" for p in planes),
    ]
    body = (
        "\n".join([*summary_lines, run_url])
        + "\n\nAgent prompt, ready to paste:\n```\n"
        + prompt(run_url, drift_text, [p.text for p in planes])
        + "\n```"
        if drifted
        else run_url
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "state").write_text("drift\n" if drifted else "clean\n")
    (out / "body.txt").write_text(slack_escape(body) + "\n")
    (out / "summary.md").write_text(
        f"## API drift: {'drift' if drifted else 'clean'}\n\n"
        + "".join(f"- {line}\n" for line in summary_lines)
        + f"\n### SDK drift\n\n```\n{render(result)}\n```\n"
        + "\n### Reference changelog\n\n```\n"
        + "\n\n".join(p.text for p in planes)
        + "\n```\n"
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
    try:
        build(
            args.out,
            args.run_url,
            {plane: getattr(args, plane) for plane in PLANES},
        )
    except Exception as exc:
        print(f"::error::could not build the API drift report: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
