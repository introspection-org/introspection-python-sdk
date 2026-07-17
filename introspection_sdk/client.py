"""REST-only Introspection client.

This module opens runners for configured runtimes and experiments, then
exposes the DP :class:`~introspection_sdk.runner.Runner` flow, **without**
importing OpenTelemetry.

Optional OTLP logs and traces are available through the ``[otel]`` extra and
remain independent of this execution client.
"""

from __future__ import annotations

__all__ = ["AsyncIntrospectionClient", "IntrospectionClient"]

import os
from uuid import UUID

import httpx

from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.auth import (
    async_service_account_token,
    service_account_token,
)
from introspection_sdk.resources.experiments import (
    AsyncExperimentHandle,
    ExperimentHandle,
    _AsyncExperiments,
    _Experiments,
)
from introspection_sdk.resources.runtimes import (
    AsyncRuntimeHandle,
    RuntimeHandle,
    _AsyncRuntimes,
    _Runtimes,
)


class IntrospectionClient:
    """REST-only Introspection client (no OpenTelemetry).

    ``client.runtime(ref).run()`` and ``client.experiment(id).run()`` mint a
    :class:`~introspection_sdk.runner.Runner` for DP traffic
    (``runner.tasks`` / ``runner.files``).

    For the OpenTelemetry-based ``track`` / ``feedback`` / ``identify``
    surface, see :class:`introspection_sdk.IntrospectionLogs` (requires
    the ``[otel]`` extra).
    """

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
        self._runtimes = _Runtimes(
            self._http,
            additional_headers=self._additional_headers,
        )
        self._experiments = _Experiments(
            self._http,
            additional_headers=self._additional_headers,
        )

    def runtime(self, ref: str | UUID) -> RuntimeHandle:
        """Open a runner from a configured runtime group slug or id."""
        return self._runtimes.handle(ref)

    def experiment(self, experiment_id: UUID) -> ExperimentHandle:
        """Open a runner from an existing experiment id."""
        return self._experiments.handle(experiment_id)

    @classmethod
    def from_service_account(
        cls,
        client_id: str,
        client_secret: str,
        project: str,
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
                project=os.environ["INTRO_PROJECT"],
            )
            runner = client.runtime("customer-agent").run()

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
            project=project,
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

    ``await client.runtime(ref).run()`` and
    ``await client.experiment(id).run()`` mint an
    :class:`~introspection_sdk.runner.AsyncRunner` for DP traffic
    (``await runner.tasks...`` / ``await runner.files...``).

    Backed by ``httpx.AsyncClient``; everything that touches the network
    is awaitable. Supports ``async with`` for deterministic teardown.

    For the OpenTelemetry-based ``track`` / ``feedback`` / ``identify``
    surface, see :class:`introspection_sdk.IntrospectionLogs` (requires
    the ``[otel]`` extra).
    """

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
        self._runtimes = _AsyncRuntimes(
            self._http,
            additional_headers=self._additional_headers,
        )
        self._experiments = _AsyncExperiments(
            self._http,
            additional_headers=self._additional_headers,
        )

    def runtime(self, ref: str | UUID) -> AsyncRuntimeHandle:
        """Open a runner from a configured runtime group slug or id."""
        return self._runtimes.handle(ref)

    def experiment(self, experiment_id: UUID) -> AsyncExperimentHandle:
        """Open a runner from an existing experiment id."""
        return self._experiments.handle(experiment_id)

    @classmethod
    async def from_service_account(
        cls,
        client_id: str,
        client_secret: str,
        project: str,
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
                project=os.environ["INTRO_PROJECT"],
            )
            runner = await client.runtime("customer-agent").run()
        """
        token = await async_service_account_token(
            client_id=client_id,
            client_secret=client_secret,
            project=project,
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
