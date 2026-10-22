#!/usr/bin/env python3
"""Check this SDK against the `x-introspection` flags of both API references.

The references are the Control Plane and Data Plane OpenAPI documents, which
introspection-cloud writes from its API surface file: each public operation
names the clients expected to call it, and this SDK is the `sdk` client. See
`scripts/api_contract/check.py` for what fails.

There is no list here of the operations this SDK covers, skips or exempts:
the cloud flags are the only classification, so a route the cloud adds for
the SDK fails here until the SDK calls it.

Not a pull-request gate: it reads the staging references over the network,
and it goes red when the API changes, which is a fact about the world and
not about the commit under review. `.github/workflows/api-contract.yml` runs
it nightly and posts the drift to Slack.

Run: uv run python scripts/check_api_contract.py
         [--controlplane URL|PATH] [--dataplane URL|PATH]
env: API_CONTRACT_CONTROLPLANE, API_CONTRACT_DATAPLANE replace the default
     staging URLs, as the flags do.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from api_contract.check import run
from api_contract.reference import load_reference, reference_source
from api_contract.source import Package

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check this SDK against the API references."
    )
    for plane in ("controlplane", "dataplane"):
        parser.add_argument(f"--{plane}", metavar="URL|PATH")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    specs = {}
    for plane in ("controlplane", "dataplane"):
        source = reference_source(plane, getattr(args, plane))
        try:
            specs[plane] = load_reference(source)
        except Exception:
            logger.exception(
                "could not read the API reference", extra={"source": source}
            )
            return 2
    result = run(Package.load(ROOT), specs)
    print(result.render())
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
