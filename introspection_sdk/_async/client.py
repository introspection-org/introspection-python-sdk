"""Re-exported by :mod:`introspection_sdk.client`."""

from __future__ import annotations

import os

import httpx2 as httpx

from introspection_sdk._http import _AsyncHttpClient
from introspection_sdk.auth import (
    AsyncCredentialProvider,
    async_service_account_token,
)
from introspection_sdk.dev_target import client_headers
from introspection_sdk.resources import (
    AsyncAnnotations,
    AsyncApiKeys,
    AsyncApplications,
    AsyncAutomations,
    AsyncConnectors,
    AsyncCredentials,
    AsyncEndpoints,
    AsyncExperiments,
    AsyncIntegrations,
    AsyncJudges,
    AsyncMembers,
    AsyncOidc,
    AsyncOrganizations,
    AsyncProjects,
    AsyncRecipes,
    AsyncRepositories,
    AsyncRuntimes,
    AsyncTags,
    AsyncTokens,
    AsyncVariables,
)
from introspection_sdk.runner_resources import (
    AsyncAAuth,
    AsyncAppConnections,
    AsyncConversations,
    AsyncEvents,
    AsyncFiles,
    AsyncImages,
    AsyncMetrics,
    AsyncShares,
    AsyncTasks,
)


class AsyncIntrospectionClient:
    # unasync: async-only (the sync twin's docstring follows)
    """Async twin of :class:`IntrospectionClient` (no OpenTelemetry).

    Use :attr:`runtimes` / :attr:`experiments` to drive the CP REST
    surface. ``await client.runtimes(slug).run()`` and
    ``await client.experiments(id).run()`` mint an
    :class:`~introspection_sdk.runner.AsyncRunner` for DP traffic
    (``await runner.tasks...`` / ``await runner.files...``).

    Backed by ``httpx.AsyncClient``; everything that touches the network
    is awaitable. Supports ``async with`` for deterministic teardown.

    For the OpenTelemetry-based ``track`` / ``feedback`` / ``identify``
    surface, see :class:`introspection_sdk.IntrospectionLogs` (requires
    the ``[otel]`` extra).
    """

    # unasync: end
    """REST-only Introspection client (no OpenTelemetry).

    Use :attr:`runtimes` / :attr:`experiments` to drive the CP REST
    surface. ``client.runtimes(slug).run()`` and
    ``client.experiments(id).run()`` mint a
    :class:`~introspection_sdk.runner.Runner` for DP traffic
    (``runner.tasks`` / ``runner.files``).

    ``credentials`` replaces the static ``token`` with a
    :class:`~introspection_sdk.auth.CredentialProvider` that is asked for
    the header on every request and renews it after a ``401`` (see
    :meth:`EmailCodeAuth.client <introspection_sdk.auth.EmailCodeAuth.client>`).
    ``transport`` is an ``httpx2`` transport used by both planes.

    For the OpenTelemetry-based ``track`` / ``feedback`` / ``identify``
    surface, see :class:`introspection_sdk.IntrospectionLogs` (requires
    the ``[otel]`` extra).
    """

    runtimes: AsyncRuntimes
    experiments: AsyncExperiments
    recipes: AsyncRecipes
    repositories: AsyncRepositories
    connectors: AsyncConnectors
    members: AsyncMembers
    annotations: AsyncAnnotations
    tags: AsyncTags
    automations: AsyncAutomations
    events: AsyncEvents
    tasks: AsyncTasks
    files: AsyncFiles
    conversations: AsyncConversations
    metrics: AsyncMetrics
    shares: AsyncShares
    connections: AsyncAppConnections
    images: AsyncImages
    projects: AsyncProjects
    api_keys: AsyncApiKeys
    applications: AsyncApplications
    credentials: AsyncCredentials
    variables: AsyncVariables
    integrations: AsyncIntegrations
    judges: AsyncJudges
    oidc: AsyncOidc
    organizations: AsyncOrganizations
    tokens: AsyncTokens
    endpoints: AsyncEndpoints
    aauth: AsyncAAuth

    def __init__(
        self,
        *,
        token: str | None = None,
        cp_session: str | None = None,
        base_api_url: str | None = None,
        dp_url: str | None = None,
        additional_headers: dict[str, str] | None = None,
        credentials: AsyncCredentialProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token or os.getenv("INTROSPECTION_TOKEN", "")
        self._base_api_url = base_api_url or os.getenv(
            "INTROSPECTION_BASE_API_URL",
            "https://api.introspection.dev",
        )
        # INTROSPECTION_DEV_TARGET rides every request as a header so it reaches
        # the paths a runner cannot: a bare `POST /v1/tasks` with a dev API key
        # mints its JWT from the key row and has no per-request claim to carry.
        # Resolved once here so every resource client below inherits it.
        self._additional_headers = client_headers(additional_headers)
        self._http = _AsyncHttpClient(
            api_url=self._base_api_url,
            token=self._token,
            cp_session=cp_session,
            additional_headers=self._additional_headers,
            transport=transport,
            credentials=credentials,
        )
        self._dp_http = _AsyncHttpClient(
            api_url=dp_url or self._base_api_url,
            token=self._token,
            additional_headers=self._additional_headers,
            transport=transport,
            credentials=credentials,
        )
        self.runtimes = AsyncRuntimes(
            self._http,
            additional_headers=self._additional_headers,
        )
        self.experiments = AsyncExperiments(
            self._http,
            additional_headers=self._additional_headers,
        )
        self.recipes = AsyncRecipes(self._http)
        self.repositories = AsyncRepositories(self._http, self._dp_http)
        self.connectors = AsyncConnectors(self._http)
        self.members = AsyncMembers(self._http)
        self.annotations = AsyncAnnotations(self._http, self._dp_http)
        self.tags = AsyncTags(self._dp_http)
        self.automations = AsyncAutomations(self._dp_http)
        self.events = AsyncEvents(self._dp_http)
        self.tasks = AsyncTasks(self._dp_http)
        self.files = AsyncFiles(self._dp_http)
        self.conversations = AsyncConversations(self._dp_http)
        self.metrics = AsyncMetrics(self._dp_http)
        self.shares = AsyncShares(self._dp_http)
        self.connections = AsyncAppConnections(self._dp_http)
        self.images = AsyncImages(self._dp_http)
        self.aauth = AsyncAAuth(self._dp_http)
        # Project administration: each route needs an org credential (a
        # member session or access token); a project API key carries none
        # of their scopes.
        self.projects = AsyncProjects(self._http)
        self.api_keys = AsyncApiKeys(self._http)
        self.applications = AsyncApplications(self._http)
        self.credentials = AsyncCredentials(self._http)
        self.variables = AsyncVariables(self._http)
        self.integrations = AsyncIntegrations(self._http)
        self.judges = AsyncJudges(self._http)
        self.oidc = AsyncOidc(self._http)
        self.organizations = AsyncOrganizations(self._http)
        self.tokens = AsyncTokens(self._http)
        self.endpoints = AsyncEndpoints(self._http)

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
        # unasync: async-only (the sync twin's docstring follows)
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
            runner = await client.runtimes("customer-agent").run()
        """
        # unasync: end
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
            runner = client.runtimes("customer-agent").run()

        The token is not auto-refreshed: it lives for ``expires_in``
        seconds, so re-mint (call this again) for long-lived processes
        once it lapses. The resolved Data Plane URL is wired into the
        annotation and project-label namespaces automatically.
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
            dp_url=token.dp_url,
            additional_headers=additional_headers,
        )

    async def shutdown(self) -> None:
        """Graceful shutdown — closes the underlying HTTP client."""
        try:
            await self._http.aclose()
            await self._dp_http.aclose()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass

    # unasync: async-only (the sync client is no context manager)
    async def __aenter__(self) -> AsyncIntrospectionClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.shutdown()

    # unasync: end
