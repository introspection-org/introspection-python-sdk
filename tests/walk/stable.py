"""``stable()``: the one normalisation rule every SDK's walk snapshots through:
ids and ``*_id`` to ``[uuid]``, ``*_at`` to ``[timestamp]``, ``*_sha`` to
``[sha]``, tokens and secrets to ``[redacted]``, any URL to ``[url]``, and a
number that moves between runs (``duration_ms``, ``*_count``, ``*_tokens``,
``max_turn``, a task's per-project ``display_index``) to ``[number]``,
asserted as a bound beside the snapshot instead.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

__all__ = ["plain", "stable"]

UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)
TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
SHA = re.compile(r"^[0-9a-f]{40}$", re.I)
UUID_ANYWHERE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
SHA_ANYWHERE = re.compile(r"\b[0-9a-f]{40}\b", re.I)
DIGEST_ANYWHERE = re.compile(r"\b[0-9a-f]{64}\b", re.I)
JWT = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
URL = re.compile(r"^https?://")
MEASURED_KEY = re.compile(
    r"(_ms$|_count$|_tokens$|^max_turn$|^display_index$)"
)
VOLATILE_KEY = re.compile(
    r"(^id$|_at$|_sha$|token$|secret$|^key$|_key$|cookie$|^url$|_url$"
    r"|^expires_in$|^client_id$|_prefix$|_suffix$|^prefix$|^key_display$"
    r"|image_tag$|_image_name$|_bytes$)"
)


def plain(value: Any) -> Any:
    """A response as JSON: a pydantic model dumped by its wire names (a
    ``SecretStr`` dumps masked, and its key makes it ``[redacted]``)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def _string(value: str, key: str) -> str:
    if UUID.match(value):
        return "[uuid]"
    if TIMESTAMP.match(value):
        return "[timestamp]"
    if SHA.match(value):
        return "[sha]"
    if JWT.match(value):
        return "[jwt]"
    if URL.match(value):
        return "[url]"
    if VOLATILE_KEY.search(key):
        return "[redacted]"
    # An identifier under an `_id` key that is not a UUID (a Restate
    # invocation, a provider response id) is volatile when it carries
    # digits; a declared name such as `mcp_server_id: hello-mcp` stays.
    if key.endswith("_id") and re.search(r"\d", value):
        return "[id]"
    # An id or a hash inside a longer value (a storage path, an image tag,
    # a digest) is volatile too; the text around it stays.
    value = UUID_ANYWHERE.sub("[uuid]", value)
    value = DIGEST_ANYWHERE.sub("[digest]", value)
    return SHA_ANYWHERE.sub("[sha]", value)


def stable(value: Any, key: str = "") -> Any:
    """Everything stable, nothing volatile (see the module)."""
    value = plain(value)
    if isinstance(value, list):
        return [stable(item) for item in value]
    if isinstance(value, dict):
        return {k: stable(v, k) for k, v in value.items()}
    if isinstance(value, str):
        return _string(value, key)
    # A measured number moves between two runs of the same script; its
    # bounds are asserted beside the snapshot instead. (`bool` is an `int`
    # in Python and never a measurement.)
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and (VOLATILE_KEY.search(key) or MEASURED_KEY.search(key))
    ):
        return "[number]"
    return value
