from __future__ import annotations

import asyncio
import ssl
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest

from introspection_sdk.proxy import ProxyConfig
from introspection_sdk.proxy.httpx2 import (
    AsyncIntrospectionTransport,
    IntrospectionTransport,
)
from tests.rest.proxy_servers import (
    ORIGIN_HOST,
    PROXY_AUTHORIZATION,
    EgressProxy,
    egress_proxy,
)

PLACEHOLDER = "sk-p***Q3xZ"


class RecordingTransport(httpx.BaseTransport):
    def __init__(self, label: str) -> None:
        self.label = label
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"route": self.label})


class AsyncRecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, label: str) -> None:
        self.label = label
        self.requests: list[httpx.Request] = []

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"route": self.label})


def test_config_reads_shared_proxy_environment() -> None:
    config = ProxyConfig.from_env(
        {
            "INTROSPECTION_EGRESS_URL": "https://egress.example",
            "INTROSPECTION_ENDPOINT_HOSTS": "api.e2b.app, API.OPENAI.COM ",
            "INTROSPECTION_RELAY_TARGET": "brightsparc",
            "HTTPS_PROXY": "http://forward.example:8080",
            "NO_PROXY": "localhost,.cluster.local",
        }
    )
    assert config.endpoint_hosts == frozenset(
        {"api.e2b.app", "api.openai.com"}
    )
    assert config.forward_proxy_url == "http://forward.example:8080"
    assert config.relay_target == "brightsparc"
    assert config.bypasses_forward_proxy("service.cluster.local")


def test_selected_host_uses_egress_and_preserves_upstream_authority() -> None:
    direct = RecordingTransport("direct")
    egress = RecordingTransport("egress")
    forward = RecordingTransport("forward")
    transport = IntrospectionTransport(
        ProxyConfig(
            egress_url="https://egress.example",
            endpoint_hosts=frozenset({"api.e2b.app"}),
            forward_proxy_url="http://forward.example",
        ),
        _direct=direct,
        _egress=egress,
        _forward=forward,
    )
    with httpx.Client(transport=transport) as client:
        response = client.post(
            "https://api.e2b.app/sandboxes?team=one",
            headers={"X-API-Key": "scoped-session-locator"},
            json={"template": "runtime"},
        )

    assert response.json() == {"route": "egress"}
    assert not direct.requests and not forward.requests
    request = egress.requests[0]
    assert str(request.url) == "https://egress.example/sandboxes?team=one"
    assert request.headers["host"] == "api.e2b.app"
    assert request.headers["x-api-key"] == "scoped-session-locator"
    assert "x-introspection-egress-host" not in request.headers
    assert "x-introspection-relay-target" not in request.headers


def test_non_endpoint_uses_forward_proxy_unless_no_proxy_matches() -> None:
    direct = RecordingTransport("direct")
    egress = RecordingTransport("egress")
    forward = RecordingTransport("forward")
    transport = IntrospectionTransport(
        ProxyConfig(
            egress_url="https://egress.example",
            endpoint_hosts=frozenset({"api.e2b.app"}),
            forward_proxy_url="http://forward.example",
            no_proxy=("cluster.local",),
        ),
        _direct=direct,
        _egress=egress,
        _forward=forward,
    )
    with httpx.Client(transport=transport) as client:
        assert client.get("https://github.com").json() == {"route": "forward"}
        assert client.get("https://api.cluster.local").json() == {
            "route": "direct"
        }


def test_relay_egress_routes_with_explicit_headers() -> None:
    egress = RecordingTransport("egress")
    transport = IntrospectionTransport(
        ProxyConfig(
            egress_url="https://egress.example:8443",
            endpoint_hosts=frozenset({"api.example.com"}),
            relay_target="brightsparc",
        ),
        _direct=RecordingTransport("direct"),
        _egress=egress,
    )
    with httpx.Client(transport=transport) as client:
        response = client.get("https://api.example.com:9443/v1/resources")

    assert response.json() == {"route": "egress"}
    request = egress.requests[0]
    assert str(request.url) == "https://egress.example:8443/v1/resources"
    assert request.headers["host"] == "egress.example:8443"
    assert request.headers["x-introspection-egress-host"] == (
        "api.example.com:9443"
    )
    assert request.headers["x-introspection-relay-target"] == "brightsparc"


def test_async_selected_host_uses_same_egress_contract() -> None:
    asyncio.run(_assert_async_selected_host_uses_same_egress_contract())


async def _assert_async_selected_host_uses_same_egress_contract() -> None:
    direct = AsyncRecordingTransport("direct")
    egress = AsyncRecordingTransport("egress")
    transport = AsyncIntrospectionTransport(
        ProxyConfig(
            egress_url="http://egress.internal:8081",
            endpoint_hosts=frozenset({"api.anthropic.com"}),
        ),
        _direct=direct,
        _egress=egress,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post("https://api.anthropic.com/v1/messages")

    assert response.json() == {"route": "egress"}
    assert str(egress.requests[0].url) == (
        "http://egress.internal:8081/v1/messages"
    )
    assert egress.requests[0].headers["host"] == "api.anthropic.com"


@pytest.mark.parametrize(
    "config",
    [
        {"endpoint_hosts": frozenset({"api.e2b.app"})},
        {"egress_url": "https://user:secret@egress.example"},
        {"egress_url": "https://egress.example/provider"},
    ],
)
def test_invalid_egress_configuration_fails_closed(
    config: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        ProxyConfig(**config)


def native_environment(proxy_url: str) -> dict[str, str]:
    return {
        "INTROSPECTION_EGRESS_PROXY_NATIVE": "1",
        "INTROSPECTION_EGRESS_URL": "https://egress.invalid",
        "INTROSPECTION_ENDPOINT_HOSTS": ORIGIN_HOST,
        "INTROSPECTION_RELAY_TARGET": "brightsparc",
        "HTTPS_PROXY": proxy_url,
        "NO_PROXY": "localhost,.cluster.local",
    }


def test_native_config_ignores_legacy_egress_contract() -> None:
    config = ProxyConfig.from_env(
        native_environment("http://session:tok@egress-gw:8080")
    )
    assert config.egress_url is None
    assert config.endpoint_hosts == frozenset()
    assert config.relay_target is None
    assert config.forward_proxy_url == "http://session:tok@egress-gw:8080"
    assert config.bypasses_forward_proxy("svc.cluster.local")


def test_unset_egress_url_never_rewrites() -> None:
    direct = RecordingTransport("direct")
    egress = RecordingTransport("egress")
    forward = RecordingTransport("forward")
    transport = IntrospectionTransport(
        ProxyConfig.from_env({"HTTPS_PROXY": "http://egress-gw:8080"}),
        _direct=direct,
        _egress=egress,
        _forward=forward,
    )
    with httpx.Client(transport=transport) as client:
        assert client.get("https://api.openai.com").json() == {
            "route": "forward"
        }
    assert not egress.requests
    assert forward.requests[0].headers["host"] == "api.openai.com"


@pytest.fixture(params=[False, True], ids=["http-proxy", "https-proxy"])
def egress(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[EgressProxy]:
    with egress_proxy(tmp_path, tls=request.param) as proxy:
        monkeypatch.setenv("SSL_CERT_FILE", str(proxy.ca_bundle))
        monkeypatch.delenv("SSL_CERT_DIR", raising=False)
        yield proxy


def test_native_request_tunnels_through_credentialed_proxy(
    egress: EgressProxy,
) -> None:
    config = ProxyConfig.from_env(native_environment(egress.proxy_url()))
    with httpx.Client(transport=IntrospectionTransport(config)) as client:
        response = client.get(
            f"https://{ORIGIN_HOST}/v1/models",
            headers={"Authorization": f"Bearer {PLACEHOLDER}"},
        )

    assert response.json() == {
        "request": "GET /v1/models HTTP/1.1",
        "host": ORIGIN_HOST,
        "authorization": f"Bearer {PLACEHOLDER}",
    }
    assert egress.connects == [(f"{ORIGIN_HOST}:443", PROXY_AUTHORIZATION)]


def test_native_async_request_tunnels_through_credentialed_proxy(
    egress: EgressProxy,
) -> None:
    config = ProxyConfig.from_env(native_environment(egress.proxy_url()))

    async def fetch() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=AsyncIntrospectionTransport(config)
        ) as client:
            return await client.get(f"https://{ORIGIN_HOST}/v1/models")

    assert asyncio.run(fetch()).json()["host"] == ORIGIN_HOST
    assert egress.connects == [(f"{ORIGIN_HOST}:443", PROXY_AUTHORIZATION)]


def test_native_request_without_proxy_credential_is_refused(
    egress: EgressProxy,
) -> None:
    config = ProxyConfig.from_env(
        native_environment(egress.proxy_url(credential=False))
    )
    with (
        httpx.Client(transport=IntrospectionTransport(config)) as client,
        pytest.raises(httpx.ProxyError, match="407"),
    ):
        client.get(f"https://{ORIGIN_HOST}/v1/models")
    assert egress.connects == [(f"{ORIGIN_HOST}:443", None)]


def test_explicit_verify_also_trusts_an_https_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    with egress_proxy(tmp_path, tls=True) as egress:
        config = ProxyConfig.from_env(native_environment(egress.proxy_url()))
        verify = ssl.create_default_context(cafile=str(egress.ca_bundle))
        transport = IntrospectionTransport(config, verify=verify)
        with httpx.Client(transport=transport) as client:
            response = client.get(f"https://{ORIGIN_HOST}/v1/models")

    assert response.json()["host"] == ORIGIN_HOST
