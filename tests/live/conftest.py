"""Fixtures for the live CRUD walks in ``tests/live``.

These reach a real deployment: a local stack seeded by
``introspection-cloud``'s ``scripts/seed_sdk_project.py`` (driven by its
``make sdk-coverage`` / ``sdk-coverage`` workflow), or a staging project.
Every test is marked ``live`` and deselected from the default run; run them
with::

    INTROSPECTION_LIVE=1 uv run pytest tests/live -m live -p no:cacheprovider

A test skips unless ``INTROSPECTION_LIVE=1``, and skips when a setting it
needs is unset, so the suite holds no state and needs no secrets to collect.

The suite authenticates as the seeded project's service account and never
reads a Data Plane URL from the environment: the ``client_credentials``
response names it, and every Data Plane client here uses that.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

from introspection_sdk import (
    IntrospectionClient,
    OAuthToken,
    service_account_token,
)
from tests.live._support import setting


@pytest.fixture(autouse=True)
def _require_live() -> None:
    if os.environ.get("INTROSPECTION_LIVE") != "1":
        pytest.skip("INTROSPECTION_LIVE is not 1")


@pytest.fixture
def base_api_url() -> str:
    return setting("INTROSPECTION_BASE_API_URL")


@pytest.fixture
def made_clients() -> Iterator[list[IntrospectionClient]]:
    made: list[IntrospectionClient] = []
    yield made
    for client in made:
        client.shutdown()


@pytest.fixture
def service_account(base_api_url: str) -> OAuthToken:
    """The service account's token, whose ``dp_url`` locates the Data
    Plane for every client that is not the service account itself."""
    token = service_account_token(
        setting("INTROSPECTION_CLIENT_ID"),
        setting("INTROSPECTION_CLIENT_SECRET"),
        setting("INTROSPECTION_PROJECT"),
        base_api_url=base_api_url,
    )
    assert token.dp_url, "the token endpoint resolved no Data Plane URL"
    return token


@pytest.fixture
def make_client(
    base_api_url: str,
    service_account: OAuthToken,
    made_clients: list[IntrospectionClient],
) -> Callable[..., IntrospectionClient]:
    """A client for ``token`` against the discovered Data Plane."""

    def make(
        token: str = "", *, cp_session: str | None = None
    ) -> IntrospectionClient:
        client = IntrospectionClient(
            token=token,
            cp_session=cp_session,
            base_api_url=base_api_url,
            dp_url=service_account.dp_url,
        )
        made_clients.append(client)
        return client

    return make


@pytest.fixture
def api_client(
    base_api_url: str, made_clients: list[IntrospectionClient]
) -> IntrospectionClient:
    """The project's service account, the SDK's primary credential; the
    constructor wires in the Data Plane URL the token response names."""
    client = IntrospectionClient.from_service_account(
        setting("INTROSPECTION_CLIENT_ID"),
        setting("INTROSPECTION_CLIENT_SECRET"),
        setting("INTROSPECTION_PROJECT"),
        base_api_url=base_api_url,
    )
    made_clients.append(client)
    return client


@pytest.fixture
def session_client(
    make_client: Callable[..., IntrospectionClient],
) -> IntrospectionClient:
    """A member's Control Plane session cookie alone, for ``members:read``,
    which no service account holds. A bearer beside the cookie is refused."""
    return make_client(cp_session=setting("INTROSPECTION_CP_SESSION"))


@pytest.fixture
def member_client(
    make_client: Callable[..., IntrospectionClient],
) -> IntrospectionClient:
    """A member's Data Plane token, for annotation tags: ``annotations:write``
    is not a service-account scope."""
    return make_client(setting("INTROSPECTION_MEMBER_TOKEN"))
