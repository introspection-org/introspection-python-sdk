"""Shared pytest fixtures and test classes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from openai import AsyncOpenAI
from testing import TestSpanExporter

from introspection_sdk import IntrospectionSpanProcessor

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
    "x-langfuse-public-key",
    "space_id",
    "cookie",
    "set-cookie",
    "openai-organization",
    "openai-project",
}

# Patterns that match real API keys/tokens in response bodies.
# Used to scrub secrets from VCR cassettes (e.g. Braintrust eval traces
# that embed env vars in their trace payloads).
_SECRET_PATTERNS = [
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), "REDACTED_OPENAI_KEY"),
    (
        re.compile(r"sk-ant-api\d+-[A-Za-z0-9_-]{20,}"),
        "REDACTED_ANTHROPIC_KEY",
    ),
    (re.compile(r"sk-D8K[A-Za-z0-9_-]{20,}"), "REDACTED_BRAINTRUST_KEY"),
    (re.compile(r"lsv2_pt_[a-f0-9]{32}_[a-f0-9]+"), "REDACTED_LANGSMITH_KEY"),
    (re.compile(r"sk-lf-[a-f0-9-]{36}"), "REDACTED_LANGFUSE_SECRET"),
    (re.compile(r"pk-lf-[a-f0-9-]{36}"), "REDACTED_LANGFUSE_PUBLIC"),
    (re.compile(r"ak-[a-f0-9-]{36}-[A-Za-z0-9_-]+"), "REDACTED_ARIZE_KEY"),
    (
        re.compile(r"intro_dev_[A-Za-z0-9_-]{20,}"),
        "REDACTED_INTROSPECTION_TOKEN",
    ),
]


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
        for pattern, replacement in _SECRET_PATTERNS:
            body["string"] = pattern.sub(replacement, body["string"])
    return response


def _scrub_request(request):
    """Scrub secrets from VCR request bodies."""
    if hasattr(request, "body") and isinstance(request.body, (str, bytes)):
        body = (
            request.body
            if isinstance(request.body, str)
            else request.body.decode("utf-8", errors="replace")
        )
        for pattern, replacement in _SECRET_PATTERNS:
            body = pattern.sub(replacement, body)
        request.body = body
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
