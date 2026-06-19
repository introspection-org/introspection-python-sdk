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

__all__ = ["AsyncIntrospectionClient", "IntrospectionClient"]

import os

import httpx

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.auth import (
    async_service_account_token,
    service_account_token,
)
from introspection_sdk.resources import (
    AsyncExperiments,
    AsyncRecipes,
    AsyncRuntimes,
    Experiments,
    Recipes,
    Runtimes,
)


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
        additional_headers: dict[str, str] | None = None,
    ) -> None:
        self._token = token or os.getenv("INTROSPECTION_TOKEN", "")
        self._base_api_url = base_api_url or os.getenv(
            "INTROSPECTION_BASE_API_URL",
            "https://api.introspection.dev",
        )
        self._additional_headers = additional_headers
        self._http = _HttpClient(
            api_url=self._base_api_url,
            token=self._token,
            additional_headers=self._additional_headers,
        )
        self.runtimes = Runtimes(
            self._http,
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

    @classmethod
    def from_service_account(
        cls,
        client_id: str,
        client_secret: str,
        project_id: str,
        *,
        scope: str | None = None,
        base_api_url: str | None = None,
        additional_headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> IntrospectionClient:
        """Authenticate as a confidential service account and return a
        ready client.

        Mints a short-lived, project-scoped CP access token via the
        ``client_credentials`` grant (see
        :func:`~introspection_sdk.auth.service_account_token`) and wires
        it in as the bearer token, so the runtime flow works exactly as
        it does with an API key::

            client = IntrospectionClient.from_service_account(
                client_id=os.environ["INTRO_SA_CLIENT_ID"],
                client_secret=os.environ["INTRO_SA_CLIENT_SECRET"],
                project_id=os.environ["INTRO_PROJECT_ID"],
            )
            runner = client.runtimes("customer-agent").run()

        The token is not auto-refreshed: it lives for ``expires_in``
        seconds, so re-mint (call this again) for long-lived processes
        once it lapses. Call
        :func:`~introspection_sdk.auth.service_account_token` directly if
        you also need the resolved ``dp_url`` (e.g. to hand a browser the
        Data Plane endpoint).
        """
        token = service_account_token(
            client_id=client_id,
            client_secret=client_secret,
            project_id=project_id,
            scope=scope,
            base_api_url=base_api_url,
            transport=transport,
        )
        return cls(
            token=token.access_token,
            base_api_url=base_api_url,
            additional_headers=additional_headers,
        )

    def shutdown(self) -> None:
        """Graceful shutdown — closes the underlying HTTP client."""
        try:
            self._http.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


class AsyncIntrospectionClient:
    """Async twin of :class:`IntrospectionClient` (no OpenTelemetry).

    Use :attr:`runtimes` / :attr:`experiments` to drive the CP REST
    surface. ``await client.runtimes(name).run()`` and
    ``await client.experiments(id).run()`` mint an
    :class:`~introspection_sdk.runner.AsyncRunner` for DP traffic
    (``await runner.tasks...`` / ``await runner.files...``).

    Backed by ``httpx.AsyncClient``; everything that touches the network
    is awaitable. Supports ``async with`` for deterministic teardown.

    For the OpenTelemetry-based ``track`` / ``feedback`` / ``identify``
    surface, see :class:`introspection_sdk.IntrospectionLogs` (requires
    the ``[otel]`` extra).
    """

    runtimes: AsyncRuntimes
    experiments: AsyncExperiments
    recipes: AsyncRecipes

    def __init__(
        self,
        *,
        token: str | None = None,
        base_api_url: str | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> None:
        self._token = token or os.getenv("INTROSPECTION_TOKEN", "")
        self._base_api_url = base_api_url or os.getenv(
            "INTROSPECTION_BASE_API_URL",
            "https://api.introspection.dev",
        )
        self._additional_headers = additional_headers
        self._http = _AsyncHttpClient(
            api_url=self._base_api_url,
            token=self._token,
            additional_headers=self._additional_headers,
        )
        self.runtimes = AsyncRuntimes(
            self._http,
            additional_headers=self._additional_headers,
        )
        self.experiments = AsyncExperiments(
            self._http,
            additional_headers=self._additional_headers,
        )
        self.recipes = AsyncRecipes(
            self._http,
            additional_headers=self._additional_headers,
        )

    @classmethod
    async def from_service_account(
        cls,
        client_id: str,
        client_secret: str,
        project_id: str,
        *,
        scope: str | None = None,
        base_api_url: str | None = None,
        additional_headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AsyncIntrospectionClient:
        """Async twin of
        :meth:`IntrospectionClient.from_service_account`.

        Mints the ``client_credentials`` token without blocking the event
        loop (see
        :func:`~introspection_sdk.auth.async_service_account_token`) and
        returns a ready :class:`AsyncIntrospectionClient`::

            client = await AsyncIntrospectionClient.from_service_account(
                client_id=os.environ["INTRO_SA_CLIENT_ID"],
                client_secret=os.environ["INTRO_SA_CLIENT_SECRET"],
                project_id=os.environ["INTRO_PROJECT_ID"],
            )
            runner = await client.runtimes("customer-agent").run()
        """
        token = await async_service_account_token(
            client_id=client_id,
            client_secret=client_secret,
            project_id=project_id,
            scope=scope,
            base_api_url=base_api_url,
            transport=transport,
        )
        return cls(
            token=token.access_token,
            base_api_url=base_api_url,
            additional_headers=additional_headers,
        )

    async def shutdown(self) -> None:
        """Graceful shutdown — closes the underlying HTTP client."""
        try:
            await self._http.aclose()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    async def __aenter__(self) -> AsyncIntrospectionClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.shutdown()
