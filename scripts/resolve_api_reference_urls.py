#!/usr/bin/env python3
"""Pick the staging API reference URLs for `.github/workflows/api-contract.yml`.

See `scripts/api_contract/urls.py` for the order of the sources. The chosen
pair goes to `$GITHUB_ENV` as `INTROSPECTION_CP_URL` and
`INTROSPECTION_DP_URL`, which `check_api_contract.py` reads, and its source
to `$GITHUB_OUTPUT` as `source=`. A pair from the dispatch payload is also
written to CACHE_DIR, which the workflow saves to the Actions cache once
`check_api_contract.py` has read both documents.

Exits 2, writing nothing, when no source names both URLs.

Run: uv run python scripts/resolve_api_reference_urls.py CACHE_DIR
env: PAYLOAD_CP_URL, PAYLOAD_DP_URL (client_payload.cp_url, .dp_url),
     INPUT_CP_URL, INPUT_DP_URL (a manual run's inputs), GITHUB_ENV,
     GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from api_contract.urls import resolve

logger = logging.getLogger(__name__)


def _append(path: str | None, text: str) -> None:
    if path:
        with open(path, "a") as out:
            out.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pick the staging API reference URLs."
    )
    parser.add_argument("cache_dir", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    env = os.environ
    try:
        urls = resolve(
            (env.get("PAYLOAD_CP_URL", ""), env.get("PAYLOAD_DP_URL", "")),
            (env.get("INPUT_CP_URL", ""), env.get("INPUT_DP_URL", "")),
            args.cache_dir,
        )
    except Exception as exc:
        print(f"::error::could not pick the API reference URLs: {exc}")
        return 2
    print(
        f"API references from the {urls.source}: {urls.cp_url}, {urls.dp_url}"
    )
    if urls.source == "payload":
        urls.save(args.cache_dir)
    _append(
        env.get("GITHUB_ENV"),
        f"INTROSPECTION_CP_URL={urls.cp_url}\n"
        f"INTROSPECTION_DP_URL={urls.dp_url}\n",
    )
    _append(env.get("GITHUB_OUTPUT"), f"source={urls.source}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
