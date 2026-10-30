"""Contract tests for ``client.remotes`` (DP ``GET /v1/remotes/connect``)."""

from __future__ import annotations

import pytest

from introspection_sdk import AuthenticationError, NotFoundError
from introspection_sdk.runner_resources import AsyncRemotes, Remotes
from introspection_sdk.runner_resources.remotes import REMOTES_CONNECT_PATH

from .conftest import FakeAPI

# What the Data Plane's `RemotesConnectDocs` serializes, abridged to one
# frame each way.
DOCS = {
    "endpoint": "/v1/remotes/connect",
    "protocol": "websocket",
    "authentication": {
        "method": "bearer",
        "description": "A development credential in Authorization",
        "example": "Authorization: Bearer <token>",
    },
    "handshake": ["hello", "attach_request"],
    "schema_version": 1,
    "encoding": "protobuf",
    "message_protocol": {
        "remote_to_cloud": [
            {"frame": "attach_request", "description": "Attach a remote"}
        ],
        "cloud_to_remote": [
            {"frame": "attach_response", "description": "The attach answer"}
        ],
    },
}


def test_connect_docs(fake_api: FakeAPI):
    fake_api.add("GET", REMOTES_CONNECT_PATH, json_body=DOCS)
    docs = Remotes(fake_api.client()).connect_docs()
    assert docs.endpoint == REMOTES_CONNECT_PATH
    assert [f.frame for f in docs.message_protocol.remote_to_cloud] == [
        "attach_request"
    ]
    assert docs.model_dump() == DOCS
    assert fake_api.last_request.method == "GET"


async def test_async_connect_docs(fake_api: FakeAPI):
    fake_api.add("GET", REMOTES_CONNECT_PATH, json_body=DOCS)
    docs = await AsyncRemotes(fake_api.async_client()).connect_docs()
    assert docs.authentication.method == "bearer"


def test_connect_docs_on_a_data_plane_without_remotes(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        REMOTES_CONNECT_PATH,
        status=404,
        json_body={"detail": "not found"},
    )
    with pytest.raises(NotFoundError):
        Remotes(fake_api.client()).connect_docs()


async def test_async_connect_docs_refuses_a_bad_token(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        REMOTES_CONNECT_PATH,
        status=401,
        json_body={"detail": "invalid token"},
    )
    with pytest.raises(AuthenticationError):
        await AsyncRemotes(fake_api.async_client()).connect_docs()
