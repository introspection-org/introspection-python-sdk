"""DP-facing :class:`Runner` returned by ``runtimes(...).run()`` and
``experiments(...).run()``.

The Runner is an agent-session with a runtime context attached. It
owns the DP endpoint + session-locator JWT minted by the CP
``/run`` call and exposes ``runner.tasks``, ``runner.files`` and the
read-only ``runner.conversations`` namespaces that target that
endpoint. The DP-side agent-session machinery
materializes the real access token from the session lookup on
each request, so the SDK does not need to drive refresh itself —
``runner.refresh()`` stays as a manual escape hatch that re-calls
CP ``/run``. ``runner.close()`` flips a local ``_closed`` flag
and tears down the underlying HTTP client; server-side revoke is
a follow-up.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from introspection_sdk._errors import RunnerExpiredError
from introspection_sdk._http import _AsyncHttpClient, _HttpClient
from introspection_sdk.runner_resources import (
    AsyncConversations,
    AsyncFiles,
    AsyncShares,
    AsyncTasks,
    Conversations,
    Files,
    Shares,
    Tasks,
)
from introspection_sdk.schemas.runner import (
    RunnerContext,
    RunnerDeployment,
    RunnerSpec,
)


class Runner:
    """Handle for talking to a running runtime/experiment on the DP.

    Constructed indirectly by ``client.runtimes(...).run()`` /
    ``client.experiments(...).run()``. Holds a private HTTP client
    pointed at ``spec.deployment.endpoint`` with the bearer JWT
    picked from ``spec.session_token``.
    """

    def __init__(
        self,
        spec: RunnerSpec,
        *,
        refresher: Callable[[], RunnerSpec],
        additional_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._spec = spec
        self._refresher = refresher
        self._additional_headers = (
            dict(additional_headers) if additional_headers else None
        )
        self._timeout = timeout
        self._closed = False
        self._http = self._build_http(spec)
        self._tasks = Tasks(self._http)
        self._files = Files(self._http)
        self._conversations = Conversations(self._http)
        self._shares = Shares(self._http)

    def _build_http(self, spec: RunnerSpec) -> _HttpClient:
        return _HttpClient(
            api_url=spec.deployment.endpoint,
            token=spec.session_token,
            additional_headers=self._additional_headers,
            timeout=self._timeout,
        )

    def _check_open(self) -> None:
        if self._closed:
            raise RunnerExpiredError(
                "Runner has been closed; create a new one via "
                "client.runtimes(...).run() or client.experiments(...).run().",
                status_code=0,
            )

    @property
    def tasks(self) -> Tasks:
        """DP ``/v1/tasks`` namespace bound to this Runner."""
        self._check_open()
        return self._tasks

    @property
    def files(self) -> Files:
        """DP ``/v1/files`` namespace bound to this Runner."""
        self._check_open()
        return self._files

    @property
    def conversations(self) -> Conversations:
        """Read-only DP ``/v1/conversations`` namespace bound to this Runner."""
        self._check_open()
        return self._conversations

    @property
    def shares(self) -> Shares:
        """DP ``/v1/shares`` read-sharing namespace bound to this Runner."""
        self._check_open()
        return self._shares

    @property
    def context(self) -> RunnerContext:
        """Resolved runtime/arm/recipe/identity/caller context."""
        return self._spec.runtime_context

    @property
    def deployment(self) -> RunnerDeployment:
        """DP deployment descriptor (endpoint, slug, region)."""
        return self._spec.deployment

    @property
    def dp_endpoint(self) -> str:
        """Convenience accessor for ``spec.deployment.endpoint``."""
        return self._spec.deployment.endpoint

    @property
    def expires_at(self) -> datetime:
        return self._spec.expires_at

    @property
    def session_id(self) -> str:
        return self._spec.session_id

    @property
    def spec(self) -> RunnerSpec:
        return self._spec

    def refresh(self) -> None:
        """Manually re-mint the RunnerSpec via CP ``/run``.

        The DP-side agent-session materializer rotates the access
        token transparently, so callers typically don't need this.
        It stays as an escape hatch when the caller wants to force
        a fresh spec (new identity, new TTL, etc.). Swaps in the
        new spec and rebuilds the underlying HTTP client; the
        previously rented client is closed best-effort.
        """
        self._check_open()
        new_spec = self._refresher()
        old_http = self._http
        self._spec = new_spec
        self._http = self._build_http(new_spec)
        self._tasks = Tasks(self._http)
        self._files = Files(self._http)
        self._conversations = Conversations(self._http)
        self._shares = Shares(self._http)
        try:
            old_http.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    def close(self) -> None:
        """Mark the Runner closed and tear down its HTTP client.

        Server-side revoke is a follow-up; for now ``close()`` just
        flips a local flag so further ``runner.tasks`` /
        ``runner.files`` calls fail loudly.
        """
        self._closed = True
        try:
            self._http.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    def __enter__(self) -> Runner:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


class AsyncRunner:
    """Async twin of :class:`Runner`.

    Constructed indirectly by ``client.runtimes(...).run()`` /
    ``client.experiments(...).run()`` on an ``AsyncIntrospectionClient``.
    Holds a private ``httpx.AsyncClient``-backed HTTP client pointed at
    ``spec.deployment.endpoint`` with the bearer JWT picked from
    ``spec.session_token``. Awaitable lifecycle: ``await runner.close()``,
    ``await runner.refresh()``, and ``async with`` support.
    """

    def __init__(
        self,
        spec: RunnerSpec,
        *,
        refresher: Callable[[], Awaitable[RunnerSpec]],
        additional_headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._spec = spec
        self._refresher = refresher
        self._additional_headers = (
            dict(additional_headers) if additional_headers else None
        )
        self._timeout = timeout
        self._closed = False
        self._http = self._build_http(spec)
        self._tasks = AsyncTasks(self._http)
        self._files = AsyncFiles(self._http)
        self._conversations = AsyncConversations(self._http)
        self._shares = AsyncShares(self._http)

    def _build_http(self, spec: RunnerSpec) -> _AsyncHttpClient:
        return _AsyncHttpClient(
            api_url=spec.deployment.endpoint,
            token=spec.session_token,
            additional_headers=self._additional_headers,
            timeout=self._timeout,
        )

    def _check_open(self) -> None:
        if self._closed:
            raise RunnerExpiredError(
                "Runner has been closed; create a new one via "
                "client.runtimes(...).run() or client.experiments(...).run().",
                status_code=0,
            )

    @property
    def tasks(self) -> AsyncTasks:
        """DP ``/v1/tasks`` namespace bound to this Runner."""
        self._check_open()
        return self._tasks

    @property
    def files(self) -> AsyncFiles:
        """DP ``/v1/files`` namespace bound to this Runner."""
        self._check_open()
        return self._files

    @property
    def conversations(self) -> AsyncConversations:
        """Read-only DP ``/v1/conversations`` namespace bound to this
        Runner."""
        self._check_open()
        return self._conversations

    @property
    def shares(self) -> AsyncShares:
        """DP ``/v1/shares`` read-sharing namespace bound to this Runner."""
        self._check_open()
        return self._shares

    @property
    def context(self) -> RunnerContext:
        """Resolved runtime/arm/recipe/identity/caller context."""
        return self._spec.runtime_context

    @property
    def deployment(self) -> RunnerDeployment:
        """DP deployment descriptor (endpoint, slug, region)."""
        return self._spec.deployment

    @property
    def dp_endpoint(self) -> str:
        """Convenience accessor for ``spec.deployment.endpoint``."""
        return self._spec.deployment.endpoint

    @property
    def expires_at(self) -> datetime:
        return self._spec.expires_at

    @property
    def session_id(self) -> str:
        return self._spec.session_id

    @property
    def spec(self) -> RunnerSpec:
        return self._spec

    async def refresh(self) -> None:
        """Manually re-mint the RunnerSpec via CP ``/run``.

        The DP-side agent-session materializer rotates the access
        token transparently, so callers typically don't need this.
        It stays as an escape hatch when the caller wants to force
        a fresh spec (new identity, new TTL, etc.). Swaps in the
        new spec and rebuilds the underlying HTTP client; the
        previously rented client is closed best-effort.
        """
        self._check_open()
        new_spec = await self._refresher()
        old_http = self._http
        self._spec = new_spec
        self._http = self._build_http(new_spec)
        self._tasks = AsyncTasks(self._http)
        self._files = AsyncFiles(self._http)
        self._conversations = AsyncConversations(self._http)
        self._shares = AsyncShares(self._http)
        try:
            await old_http.aclose()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    async def close(self) -> None:
        """Mark the Runner closed and tear down its HTTP client.

        Server-side revoke is a follow-up; for now ``close()`` just
        flips a local flag so further ``runner.tasks`` /
        ``runner.files`` calls fail loudly.
        """
        self._closed = True
        try:
            await self._http.aclose()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    async def __aenter__(self) -> AsyncRunner:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()


__all__ = ["AsyncRunner", "Runner"]
