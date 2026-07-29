"""Development-target resolution — which `introspection dev` server this
process's tasks should reach.

Two developers can run `introspection dev` against one shared Runtime. A task
created by a shared application credential carries no developer, so the
platform cannot tell their machines apart; the caller names one instead.
`introspection dev` prints the value to set::

    serving as: roland
    for your app: INTROSPECTION_DEV_TARGET=roland

Carried as a request header rather than on the runner's ``caller`` payload:
``caller`` is descriptive metadata the platform never acts on, and a target is
a per-request selector the platform does act on. Keeping them apart is what
lets ``caller`` stay a free-form bag, and the header is the only transport that
reaches a bare ``POST /v1/tasks`` with a dev API key, whose JWT is minted from
the key row with no per-request input path.

Deliberately env-only, with no ``getpass.getuser()`` fallback. Defaulting to
the local username would be zero-config on a laptop and wrong everywhere else:
a process running in a shared development deployment under an account like
``app`` would silently name a machine nobody is serving and fail closed, where
today it reaches the one connected dev server. The CLI defaults to the username
because it is naming *itself* and always runs on the developer's machine; this
names *someone else's* machine and can run anywhere.

Inert outside development: the Data Plane consults a target only on the
development pin path, so a stray value in staging or production is ignored.
"""

import os
from urllib.parse import quote

__all__ = [
    "DEV_TARGET_ENV",
    "DEV_TARGET_HEADER",
    "dev_target_headers",
    "resolve_dev_target",
]

#: Header carrying the target on requests that have no runner to ride.
DEV_TARGET_HEADER = "x-introspection-dev-target"

#: The env var `introspection dev` prints, read by both the CLI and this SDK.
DEV_TARGET_ENV = "INTROSPECTION_DEV_TARGET"


def resolve_dev_target() -> str | None:
    """The development target for this process, or None when unset.

    Percent-encoded, because the value becomes an HTTP header and a header is
    bytes: ``httpx`` raises outright on a non-ASCII header value, so a login
    name like ``andré`` would otherwise fail the request rather than route it.
    An ordinary ASCII name encodes to itself and is unaffected.

    Safe to send encoded because the Data Plane decodes before it normalizes,
    so ``andré`` and ``andr%C3%A9`` land on the same target as the ``--as
    andré`` the CLI advertises over protobuf, where no encoding is needed.
    """
    raw = os.getenv(DEV_TARGET_ENV)
    trimmed = raw.strip() if raw else ""
    return quote(trimmed, safe="") or None


def dev_target_headers(
    additional_headers: dict[str, str] | None,
) -> dict[str, str] | None:
    """``additional_headers`` with the development target merged in.

    Merged *under* the caller's own headers, so an explicitly configured
    ``x-introspection-dev-target`` still wins. Returns the input unchanged when
    no target is set, so a client that never opts in carries nothing new.
    """
    target = resolve_dev_target()
    if target is None:
        return additional_headers
    return {DEV_TARGET_HEADER: target, **(additional_headers or {})}
