"""Shared retry policy and backoff math for the REST clients.

One private home for the pieces the unary clients (:mod:`._http`) and
the resumable run stream (:mod:`.resumable`) both need — the mirror of
``backoff.ts`` in the JS SDK and ``api::backoff`` in the Rust SDK:

* :func:`_retry_delay` — the capped-exponential step with ``Retry-After``
  honoured as a floor when present (never required).
* :func:`_is_retryable_status` — the unary retry decision. ``429`` is
  retryable for every method (the request was rejected before it was
  processed, so re-sending is side-effect-safe even for writes).
  ``502``/``503``/``504`` are transient gateway/upstream failures where
  the request *may* have been processed, so they are retried only for
  idempotent (``GET``) calls. The decision is status-based — a
  ``Retry-After`` header only affects the delay, never whether we retry.

The stream in :mod:`.resumable` shares only the delay math; its retry
*decisions* (reconnect budget, readiness ``429`` handling) are its own.
"""

from __future__ import annotations

#: Cap on the capped-exponential retry backoff (seconds).
_MAX_RETRY_BACKOFF = 10.0

#: Transient 5xx statuses retried only on idempotent (``GET``) calls.
_IDEMPOTENT_RETRY_STATUSES = frozenset({502, 503, 504})


def _retry_delay(
    attempt: int, retry_after: float | None, base: float
) -> float:
    """``Retry-After`` as the floor of a capped-exponential step (``base * 2^n``)."""
    exp = min(base * (2**attempt), _MAX_RETRY_BACKOFF)
    return max(retry_after or 0.0, exp)


def _is_retryable_status(status: int, idempotent: bool) -> bool:
    """Whether a unary response status may be transparently retried.

    ``429`` → always; ``502``/``503``/``504`` → only when ``idempotent``
    (the request method is ``GET``). Everything else is surfaced.
    """
    if status == 429:
        return True
    return idempotent and status in _IDEMPOTENT_RETRY_STATUSES
