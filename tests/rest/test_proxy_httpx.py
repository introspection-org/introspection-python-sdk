from __future__ import annotations

import httpx

from introspection_sdk.proxy import ProxyConfig
from introspection_sdk.proxy.httpx import IntrospectionTransport


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, label: str) -> None:
        self.label = label
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"route": self.label})


def test_legacy_httpx_import_uses_shared_egress_contract() -> None:
    direct = RecordingTransport("direct")
    egress = RecordingTransport("egress")
    transport = IntrospectionTransport(
        ProxyConfig(
            egress_url="https://egress.example",
            endpoint_hosts=frozenset({"api.e2b.app"}),
        ),
        _direct=direct,
        _egress=egress,
    )

    with httpx.Client(transport=transport) as client:
        response = client.post(
            "https://api.e2b.app/sandboxes",
            headers={"X-API-Key": "scoped-session-locator"},
        )

    assert response.json() == {"route": "egress"}
    assert not direct.requests
    assert str(egress.requests[0].url) == "https://egress.example/sandboxes"
    assert egress.requests[0].headers["host"] == "api.e2b.app"
    assert egress.requests[0].headers["x-api-key"] == (
        "scoped-session-locator"
    )
