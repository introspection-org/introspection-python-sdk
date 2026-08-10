"""What the REST clients put in `User-Agent`.

Both OTLP streams identified the SDK and its release; REST did not, so API
traffic arrived as the bare `python-httpx/<version>` default with nothing
tying a request to a client or a release. Construction wires the header onto
every namespace but issues no requests, so these run fully offline.
"""

from __future__ import annotations

import pytest

from introspection_sdk.client import (
    AsyncIntrospectionClient,
    IntrospectionClient,
)
from introspection_sdk.dev_target import DEV_TARGET_ENV, client_headers
from introspection_sdk.version import USER_AGENT


def test_the_agent_names_the_sdk_and_its_release():
    assert USER_AGENT.startswith("introspection-sdk/")
    assert USER_AGENT != "introspection-sdk/"


@pytest.mark.parametrize(
    "make", [IntrospectionClient, AsyncIntrospectionClient]
)
def test_both_clients_send_it(make):
    client = make(token="t")
    assert client._additional_headers["User-Agent"] == USER_AGENT


def test_a_caller_can_still_override_it():
    client = IntrospectionClient(
        token="t", additional_headers={"User-Agent": "my-app/1.0"}
    )
    assert client._additional_headers["User-Agent"] == "my-app/1.0"


def test_it_does_not_displace_the_dev_target_header(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(DEV_TARGET_ENV, "roland")
    headers = client_headers(None)
    assert headers["User-Agent"] == USER_AGENT
    assert headers["x-introspection-dev-target"] == "roland"
