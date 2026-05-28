"""Shared pytest fixtures and test classes."""

from __future__ import annotations

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


SENSITIVE_HEADERS = {
    "authorization",
    "api-key",
    "api_key",
    "x-api-key",
    "x-bt-api-key",
    "x-goog-api-key",
    "x-langfuse-public-key",
    "space_id",
    "cookie",
    "set-cookie",
    "openai-organization",
    "openai-project",
    "anthropic-organization-id",
}


def _scrub_response(response):
    """Remove sensitive headers and scrub secrets from VCR response recordings."""
    headers = response.get("headers", {})
    for key in list(headers):
        if key.lower() in SENSITIVE_HEADERS:
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
    """Scrub secrets from VCR request bodies and URIs."""
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
