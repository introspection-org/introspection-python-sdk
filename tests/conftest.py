"""Shared pytest fixtures and test classes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from openai import AsyncOpenAI
from testing import TestSpanExporter

from introspection_sdk import IntrospectionSpanProcessor
from introspection_sdk.testing.redaction import redact_secrets

HAS_AGENTS = True
try:
    from introspection_sdk import IntrospectionTracingProcessor
except RuntimeError:
    HAS_AGENTS = False
    if TYPE_CHECKING:
        from introspection_sdk import IntrospectionTracingProcessor


@dataclass
class CaptureSpanProcessor:
    """Holds the span exporter and processor for testing."""

    exporter: TestSpanExporter
    processor: IntrospectionSpanProcessor


@dataclass
class CaptureTracingProcessor:
    """Holds the span exporter and tracing processor for testing."""

    exporter: TestSpanExporter
    processor: IntrospectionTracingProcessor


# Kept in sync with the JS SDK's cassette scrubbing (introspection-js-sdk
# ``tests/polly-setup.ts`` SENSITIVE_HEADERS) so both SDKs redact the same
# credential headers from recordings.
SENSITIVE_HEADERS = {
    "authorization",
    "api-key",
    "api_key",
    "x-api-key",
    "x-bt-api-key",
    "x-stainless-api-key",
    "anthropic-api-key",
    "anthropic-organization-id",
    "x-goog-api-key",
    "x-goog-user-project",
    "x-langfuse-public-key",
    "space_id",
    "cookie",
    "set-cookie",
    "openai-organization",
    "openai-project",
}

# Belt-and-suspenders over the explicit set (mirrors the JS
# ``SENSITIVE_HEADER_PATTERN``): any header whose name *looks* like a credential
# is redacted too, so a new provider's auth header can never slip into a
# recording just because it wasn't enumerated above.
SENSITIVE_HEADER_RE = re.compile(
    r"(authorization|api[-_]?key|access[-_]?token|refresh[-_]?token|\btoken\b"
    r"|secret|password|credential|cookie|x-goog-user-project|session)",
    re.IGNORECASE,
)


def _is_sensitive_header(name: str) -> bool:
    return name.lower() in SENSITIVE_HEADERS or bool(
        SENSITIVE_HEADER_RE.search(name)
    )


def _scrub_response(response):
    """Remove sensitive headers and scrub secrets from VCR response recordings."""
    headers = response.get("headers", {})
    for key in list(headers):
        if _is_sensitive_header(key):
            del headers[key]
    # Scrub secrets from response body (e.g. Braintrust eval traces embed env vars)
    body = response.get("body", {})
    if (
        isinstance(body, dict)
        and "string" in body
        and isinstance(body["string"], str)
    ):
        body["string"] = redact_secrets(body["string"])
    return response


def _scrub_request(request):
    """Scrub secrets from VCR request headers, bodies, and URIs."""
    if hasattr(request, "headers") and request.headers:
        for key in list(request.headers):
            if _is_sensitive_header(key):
                del request.headers[key]
    if hasattr(request, "body") and isinstance(request.body, (str, bytes)):
        body = (
            request.body
            if isinstance(request.body, str)
            else request.body.decode("utf-8", errors="replace")
        )
        request.body = redact_secrets(body)
    # Some providers (e.g. Google) historically accepted an API key as a
    # ``?key=...`` query parameter; scrub it from the URI too.
    if hasattr(request, "uri") and isinstance(request.uri, str):
        request.uri = redact_secrets(request.uri)
    return request


@pytest.fixture(scope="module")
def vcr_config():
    """Filter sensitive headers and scrub secrets from VCR cassette recordings."""
    return {
        "filter_headers": list(SENSITIVE_HEADERS),
        "before_record_response": _scrub_response,
        "before_record_request": _scrub_request,
        "decode_compressed_response": True,
    }


@pytest.fixture
def openai_model() -> str:
    return "gpt-5-nano"


@pytest.fixture
def anthropic_model() -> str:
    return "claude-haiku-4-5"


@pytest.fixture
def openai_async_client() -> AsyncOpenAI:
    """Plain OpenAI async client (not instrumented)."""
    return AsyncOpenAI()
