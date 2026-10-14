from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from introspection_sdk.proxy import ProxyConfig
from introspection_sdk.proxy.httpx import IntrospectionTransport
from tests.rest.proxy_servers import (
    ORIGIN_HOST,
    PROXY_AUTHORIZATION,
    egress_proxy,
)


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


@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
def test_legacy_httpx_native_request_uses_credentialed_proxy(
    tls: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with egress_proxy(tmp_path, tls=tls) as egress:
        monkeypatch.setenv("SSL_CERT_FILE", str(egress.ca_bundle))
        monkeypatch.delenv("SSL_CERT_DIR", raising=False)
        config = ProxyConfig.from_env(
            {
                "INTROSPECTION_EGRESS_PROXY_NATIVE": "1",
                "INTROSPECTION_EGRESS_URL": "https://egress.invalid",
                "INTROSPECTION_ENDPOINT_HOSTS": ORIGIN_HOST,
                "HTTPS_PROXY": egress.proxy_url(),
            }
        )
        with httpx.Client(transport=IntrospectionTransport(config)) as client:
            response = client.get(f"https://{ORIGIN_HOST}/sandboxes")

    assert response.json()["request"] == "GET /sandboxes HTTP/1.1"
    assert egress.connects == [(f"{ORIGIN_HOST}:443", PROXY_AUTHORIZATION)]
