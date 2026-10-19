"""Fixtures for the live CRUD walks in ``tests/live``.

These reach a real deployment: a local stack seeded by
``introspection-cloud``'s ``scripts/seed_sdk_project.py`` (driven by its
``make sdk-coverage`` / ``sdk-coverage`` workflow), or a staging project.
Every test is marked ``live`` and deselected from the default run; run them
with::

    INTROSPECTION_LIVE=1 uv run pytest tests/live -m live -p no:cacheprovider

A test skips unless ``INTROSPECTION_LIVE=1``, and skips when a setting it
needs is unset, so the suite holds no state and needs no secrets to collect.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest

from introspection_sdk import IntrospectionClient
from tests.live._support import setting


@pytest.fixture(autouse=True)
def _require_live() -> None:
    if os.environ.get("INTROSPECTION_LIVE") != "1":
        pytest.skip("INTROSPECTION_LIVE is not 1")


def _client(
    token: str, *, cp_session: str | None = None
) -> IntrospectionClient:
    return IntrospectionClient(
        token=token,
        cp_session=cp_session,
        base_api_url=os.environ.get("INTROSPECTION_BASE_API_URL"),
        dp_url=os.environ.get("INTROSPECTION_DP_URL"),
    )


@pytest.fixture
def make_client() -> Iterator[Callable[..., IntrospectionClient]]:
    made: list[IntrospectionClient] = []

    def make(
        token: str, *, cp_session: str | None = None
    ) -> IntrospectionClient:
        client = _client(token, cp_session=cp_session)
        made.append(client)
        return client

    yield make
    for client in made:
        client.shutdown()


@pytest.fixture
def api_client(
    make_client: Callable[..., IntrospectionClient],
) -> IntrospectionClient:
    """The project's API key, the SDK's primary credential."""
    return make_client(setting("INTROSPECTION_TOKEN"))


@pytest.fixture
def session_client(
    make_client: Callable[..., IntrospectionClient],
) -> IntrospectionClient:
    """A member's Control Plane session, for member-authored CP routes."""
    return make_client(
        setting("INTROSPECTION_TOKEN"),
        cp_session=setting("INTROSPECTION_CP_SESSION"),
    )


@pytest.fixture
def member_client(
    make_client: Callable[..., IntrospectionClient],
) -> IntrospectionClient:
    """A member's Data Plane token, for the DP writes no API key capability
    grants (automations, annotation tags, share deletes)."""
    return make_client(setting("INTROSPECTION_MEMBER_TOKEN"))
