"""Where the staging API references are: the Control Plane and Data Plane
base URLs a run reads `/openapi.json` under.

introspection-cloud's "API Reference Deployed" workflow sends both in the
`api-reference-deployed` dispatch (`client_payload.cp_url`, `.dp_url`), and
the workflow keeps the newest pair in the Actions cache for the runs that
carry none. A run takes the first of these that names both:

1. the dispatch payload, which is then saved to the cache;
2. a manual run's `cp_url` / `dp_url` inputs;
3. the pair the newest dispatch saved.

A source naming only one of the two is an error, not a fall-through, so a
half-filled manual run never mixes its URL with a cached one. With no
source at all the run fails and says how to record a pair.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

__all__ = [
    "CACHE_FILE",
    "MissingUrls",
    "ReferenceUrls",
    "load_cached",
    "resolve",
]

#: The file, inside the cached directory, that holds the newest pair.
CACHE_FILE = "urls.json"

logger = logging.getLogger(__name__)


class MissingUrls(RuntimeError):
    """No source names both base URLs."""

    def __init__(self) -> None:
        super().__init__(
            "no staging reference URLs recorded yet: run introspection-cloud's "
            '"API Reference Deployed" workflow by hand (it dispatches here and '
            "refills the cache), or run this workflow by hand with its cp_url "
            "and dp_url inputs"
        )


@dataclass(frozen=True)
class ReferenceUrls:
    cp_url: str
    dp_url: str
    #: Where the pair came from: `payload`, `input` or `cache`.
    source: str

    def save(self, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / CACHE_FILE).write_text(
            json.dumps({"cp_url": self.cp_url, "dp_url": self.dp_url}) + "\n"
        )


def _checked(name: str, value: str) -> str:
    """An http(s) base URL with nothing that could break out of a line."""
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or any(char.isspace() for char in value)
    ):
        raise ValueError(f"{name} is not an http(s) URL: {value!r}")
    return value.rstrip("/")


def _pair(source: str, cp_url: str, dp_url: str) -> ReferenceUrls | None:
    """Both URLs, None when neither is set; one alone is an error."""
    cp_url, dp_url = cp_url.strip(), dp_url.strip()
    if not cp_url and not dp_url:
        return None
    if not cp_url or not dp_url:
        missing = "cp_url" if not cp_url else "dp_url"
        raise ValueError(f"the {source} names no {missing}: pass both or none")
    return ReferenceUrls(
        cp_url=_checked(f"{source} cp_url", cp_url),
        dp_url=_checked(f"{source} dp_url", dp_url),
        source=source,
    )


def load_cached(cache_dir: Path) -> ReferenceUrls | None:
    """The pair the newest dispatch saved, None when there is none."""
    path = cache_dir / CACHE_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return _pair("cache", data.get("cp_url", ""), data.get("dp_url", ""))


def resolve(
    payload: tuple[str, str], inputs: tuple[str, str], cache_dir: Path
) -> ReferenceUrls:
    """The first source naming both URLs; raises `MissingUrls` with none."""
    urls = (
        _pair("payload", *payload)
        or _pair("input", *inputs)
        or load_cached(cache_dir)
    )
    if urls is None:
        raise MissingUrls
    logger.info("resolved API reference URLs", extra={"source": urls.source})
    return urls
