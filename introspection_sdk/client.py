"""REST-only Introspection client.

This module exposes the CP REST surface
(:class:`~introspection_sdk.resources.Runtimes`,
:class:`~introspection_sdk.resources.Experiments`) plus the DP
:class:`~introspection_sdk.runner.Runner` flow, **without** importing
OpenTelemetry.

For OpenTelemetry-based emission of ``track`` / ``feedback`` /
``identify`` events, install the ``[otel]`` extra and use
:class:`introspection_sdk.IntrospectionLogs`. For trace export
(span / tracing processors, LLM SDK instrumentors), pick the relevant
processors from :mod:`introspection_sdk.otel`.
"""

from __future__ import annotations

__all__ = ["IntrospectionClient"]

import os

from introspection_sdk._http import _HttpClient
from introspection_sdk.resources import Experiments, Recipes, Runtimes


class IntrospectionClient:
    """REST-only Introspection client (no OpenTelemetry).

    Use :attr:`runtimes` / :attr:`experiments` to drive the CP REST
    surface. ``client.runtimes(name).run()`` and
    ``client.experiments(id).run()`` mint a
    :class:`~introspection_sdk.runner.Runner` for DP traffic
    (``runner.tasks`` / ``runner.files``).

    For the OpenTelemetry-based ``track`` / ``feedback`` / ``identify``
    surface, see :class:`introspection_sdk.IntrospectionLogs` (requires
    the ``[otel]`` extra).
    """

    runtimes: Runtimes
    experiments: Experiments
    recipes: Recipes

    def __init__(
        self,
        *,
        token: str | None = None,
        base_api_url: str | None = None,
        project_id: str | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> None:
        self._token = token or os.getenv("INTROSPECTION_TOKEN", "")
        self._base_api_url = base_api_url or os.getenv(
            "INTROSPECTION_BASE_API_URL",
            "https://api.introspection.dev",
        )
        self._project_id = project_id or os.getenv("INTROSPECTION_PROJECT_ID")
        self._additional_headers = additional_headers
        self._http = _HttpClient(
            api_url=self._base_api_url,
            token=self._token,
            additional_headers=self._additional_headers,
        )
        self.runtimes = Runtimes(
            self._http,
            default_project_id=self._project_id,
            additional_headers=self._additional_headers,
        )
        self.experiments = Experiments(
            self._http,
            additional_headers=self._additional_headers,
        )
        self.recipes = Recipes(
            self._http,
            additional_headers=self._additional_headers,
        )

    def shutdown(self) -> None:
        """Graceful shutdown — closes the underlying HTTP client."""
        try:
            self._http.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
