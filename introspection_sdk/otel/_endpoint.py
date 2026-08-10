"""OTLP endpoint derivation, shared by the span and log exporters.

Both surfaces read the same ``INTROSPECTION_BASE_OTEL_URL`` / ``base_url``
setting, so both have to accept the same spellings of it. Keeping the rule in
one place is what stops a base URL that works for traces from producing
``.../v1/traces/v1/logs`` for logs.
"""

from __future__ import annotations

from urllib.parse import urljoin

__all__ = ["SIGNAL_PATHS", "otlp_endpoint"]

#: Signal name -> its OTLP path suffix.
SIGNAL_PATHS = {
    "traces": "v1/traces",
    "logs": "v1/logs",
}


def otlp_endpoint(base_url: str, signal: str) -> str:
    """Return the OTLP endpoint for ``signal`` under ``base_url``.

    Accepts a bare base (``https://otel.introspection.dev``), a base with a
    path prefix (``https://gateway.internal/otlp``), or a base that already
    carries any signal's suffix — the documented form in
    :class:`~introspection_sdk.config.AdvancedOptions` is
    ``http://localhost:5418/v1/traces``, and that same value has to yield
    ``http://localhost:5418/v1/logs`` here rather than appending twice.

    Args:
        base_url: The configured collector base URL.
        signal: ``"traces"`` or ``"logs"``.

    Returns:
        The absolute endpoint URL.

    Raises:
        ValueError: If ``signal`` is not a known signal.
    """
    try:
        suffix = SIGNAL_PATHS[signal]
    except KeyError:
        raise ValueError(f"Unknown OTLP signal: {signal!r}") from None

    trimmed = base_url.rstrip("/")
    for known in SIGNAL_PATHS.values():
        if trimmed.endswith("/" + known):
            trimmed = trimmed[: -len(known) - 1]
            break

    # Relative join: an absolute "/v1/traces" would discard a path prefix on
    # the base URL (…/otlp -> …/v1/traces instead of …/otlp/v1/traces).
    return urljoin(trimmed + "/", suffix)
