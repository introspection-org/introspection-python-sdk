"""Shared retry/backoff primitives.

Both the unary REST retry path (:mod:`introspection_sdk._http`) and the
resumable run-stream (:mod:`introspection_sdk.resumable`) back off the same
way — a capped-exponential delay with the server's ``Retry-After`` as a
floor — so the math and the cap live here once rather than being copied into
each. The *retry decision* (which statuses, which methods, readiness vs
severance) stays in each caller, since those differ.
"""

from __future__ import annotations

#: Cap on any single backoff step (seconds).
MAX_BACKOFF = 10.0


def backoff_delay(
    attempt: int, retry_after: float | None, base: float
) -> float:
    """Capped-exponential backoff: ``base * 2^attempt``, clamped to
    :data:`MAX_BACKOFF`, with ``retry_after`` used as the floor when present."""
    exp = min(base * (2**attempt), MAX_BACKOFF)
    return max(retry_after or 0.0, exp)
