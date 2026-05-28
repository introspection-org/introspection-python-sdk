"""Single source of truth for the API keys, tokens, and UUIDs that both
``tests/conftest.py`` (HTTP cassettes) and :mod:`claude_vcr` (subprocess IPC)
must scrub before anything touches disk. Transport-specific ids stay with
their transport."""

from __future__ import annotations

__all__ = [
    "SECRET_PATTERNS",
    "UUID_PLACEHOLDER",
    "UUID_RE",
    "redact_secrets",
]

import re

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), "REDACTED_OPENAI_KEY"),
    (re.compile(r"AIza[A-Za-z0-9_-]{35}"), "REDACTED_GOOGLE_KEY"),
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

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
UUID_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def redact_secrets(text: str) -> str:
    """Apply every shared secret pattern to *text* and return the result."""
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
