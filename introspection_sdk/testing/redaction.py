"""Cassette scrubbing: the one list of secret shapes every SDK redacts.

``introspection-js-sdk/tests/polly-setup.ts`` names this module as the other
half of its ``SECRET_PATTERNS``: identical regexes and identical
``REDACTED_*`` placeholders, so a secret is scrubbed the same way whether it
lands in a JS or a Python cassette, and a body scrubbed by one SDK's record
run matches the other SDK's request scrubbed here. Keep the two lists in
lockstep. Scrubbing runs on what is recorded and, before matching, on what
is sent; it never rewrites a committed cassette on replay.
"""

from __future__ import annotations

import re

__all__ = [
    "REDACTED",
    "SECRET_PATTERNS",
    "SENSITIVE_HEADERS",
    "SENSITIVE_HEADER_PATTERN",
    "is_sensitive_header",
    "scrub_secrets",
]

#: The value a credential-bearing header is recorded as.
REDACTED = "REDACTED"

#: Headers that carry a credential, redacted before a recording is written.
SENSITIVE_HEADERS = frozenset(
    {
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
        "space_id",
        "cookie",
        "set-cookie",
        "openai-organization",
        "openai-project",
    }
)

#: Belt and braces over the list: any header whose name looks like a
#: credential is redacted too, so a new provider's auth header never slips
#: into a recording for not being enumerated.
SENSITIVE_HEADER_PATTERN = re.compile(
    r"(authorization|api[-_]?key|access[-_]?token|refresh[-_]?token"
    r"|\btoken\b|secret|password|credential|cookie|x-goog-user-project"
    r"|session)",
    re.IGNORECASE,
)

#: Secret shapes and their placeholders, in the order they apply.
SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"), "REDACTED_OPENAI_KEY"),
    (re.compile(r"AIza[A-Za-z0-9_-]{35}"), "REDACTED_GOOGLE_KEY"),
    (
        re.compile(r"sk-ant-api\d+-[A-Za-z0-9_-]{20,}"),
        "REDACTED_ANTHROPIC_KEY",
    ),
    (
        re.compile(r"intro_dev_[A-Za-z0-9_-]{20,}"),
        "REDACTED_INTROSPECTION_TOKEN",
    ),
    # The platform's own credentials as the walk records them: every JWT the
    # planes mint (access, session, runner, member tokens), a project API key
    # in any environment, and the one-time plaintext of an application secret
    # or a credential, in a JSON body or a form field.
    (
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
        "REDACTED_JWT",
    ),
    (
        re.compile(r"intro_[a-z]+_[A-Za-z0-9_-]{20,}"),
        "REDACTED_INTROSPECTION_KEY",
    ),
    (
        re.compile(r'("(?:client_secret|secret|api_key)"\s*:\s*")[^"]+(")'),
        r"\1REDACTED_SECRET\2",
    ),
    (re.compile(r"(client_secret=)[^&\s]+"), r"\1REDACTED_SECRET"),
)


def scrub_secrets(text: str) -> str:
    """Replace every secret shape in ``text`` with its placeholder."""
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def is_sensitive_header(name: str) -> bool:
    """Whether a header named ``name`` carries a credential."""
    lowered = name.lower()
    return lowered in SENSITIVE_HEADERS or bool(
        SENSITIVE_HEADER_PATTERN.search(lowered)
    )
