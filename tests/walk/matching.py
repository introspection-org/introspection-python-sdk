"""How a replayed request finds its recording, and what a record run keeps.

Matching is method + URL (scheme, host, port, path, query) + body, headers
ignored (introspection-cloud ``docs/design/sdk-end-to-end-walk.md`` §5). The
body is compared as what it means, not as bytes:

- JSON as parsed JSON, so key order and whitespace never matter;
- a form (``application/x-www-form-urlencoded``) as its fields;
- multipart as its fields, never the boundary.

Each side is scrubbed (:mod:`introspection_sdk.testing.redaction`) before it
is compared, in record and replay alike, so a secret the recording holds as
``REDACTED_SECRET`` matches the plaintext the SDK sends. Identical requests
are consumed in recorded order: VCR plays the first unplayed match and
``allow_playback_repeats`` stays off.

Normalisations, each one narrow and the reason the request still means the
same thing:

- **A query parameter at the route's own default.** The Python SDK's list
  methods send ``limit`` and ``include_total`` on every page where the JS SDK
  sends nothing; when the value sent is the one the route defaults to
  (:data:`ROUTE_DEFAULTS`, read off the API's route signatures), the request
  asks for what the bare one does. Any other value still mismatches.

- **A ``null`` member is an absent member.** The Python SDK leaves unset
  fields off the wire (``_body`` dumps with ``exclude_none``) where the JS SDK
  sends some as ``null``; the API reads both as unset.
- **A body field at the route's own default.** The Python SDK always sends
  ``member_type`` on ``POST /v1/members``; ``business`` is the model's
  default (:data:`BODY_DEFAULTS`), so the JS SDK's body without it asks the
  same.
- **An empty JSON object is no body.** The JS SDK posts ``{}`` to the
  bodiless transitions (``/start``, ``/end``, ``/cancel``) where the Python
  SDK posts nothing; neither route reads a body.
- **A multipart body the recording holds no fields for.** Polly records a
  ``FormData`` upload from Node as a bare ``postData`` with no text and no
  params (the JS walk's file-version upload), so the one thing left to
  compare is that the request is multipart at all.
"""

from __future__ import annotations

import copy
import difflib
import json
import re
from typing import Any
from urllib.parse import parse_qsl

from vcr.request import Request

from introspection_sdk.testing.redaction import (
    REDACTED,
    is_sensitive_header,
    scrub_secrets,
)

from .har import MULTIPART_FIELDS, multipart_fields

__all__ = [
    "MATCH_ON",
    "BODY_DEFAULTS",
    "ROUTE_DEFAULTS",
    "body_meaning",
    "scrub_request",
    "scrub_response",
    "semantic_body",
    "semantic_query",
]

#: The matchers the walk's cassette uses, by VCR name (``semantic_body`` is
#: registered under that name).
MATCH_ON = (
    "method",
    "scheme",
    "host",
    "port",
    "path",
    "semantic_query",
    "semantic_body",
)

#: The query parameters a route reads as absent at these values: the
#: ``Query(...)`` defaults of the routes the walk lists (introspection-cloud
#: ``apps/{controlplane,dataplane}-api/.../api/v1``). A route not listed
#: gets no allowance.
ROUTE_DEFAULTS: tuple[tuple[re.Pattern[str], dict[str, str]], ...] = (
    (
        re.compile(r"^/v1/(tasks|files|files/[^/]+/versions)$"),
        {"limit": "100", "include_total": "false"},
    ),
    (
        re.compile(
            r"^/v1/(automations|annotations|tags|conversations"
            r"|events|runtimes|experiments)$"
        ),
        {"limit": "100"},
    ),
    (
        re.compile(r"^/v1/shares$"),
        {"limit": "100", "created_by_me": "false", "granted_to_me": "false"},
    ),
    (re.compile(r"^/v1/conversations/[^/]+/items$"), {"limit": "200"}),
)


def _content_type(request: Request) -> str:
    return (request.headers.get("content-type") or "").lower()


def _text(body: Any) -> str | None:
    if body is None:
        return None
    if isinstance(body, str):
        return body
    try:
        return bytes(body).decode("utf-8")
    except UnicodeDecodeError:
        return None


def _drop_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value]
    return value


def body_meaning(request: Request) -> tuple[str, Any]:
    """What a request's body says, as a ``(kind, value)`` pair to compare."""
    raw = request.body or b""
    if not raw:
        return ("empty", None)
    kind = _content_type(request)
    text = _text(raw)
    if kind.startswith(MULTIPART_FIELDS):
        fields = json.loads(text or "[]")
        return (
            "multipart",
            sorted(json.dumps(f, sort_keys=True) for f in fields),
        )
    if kind.startswith("multipart/form-data"):
        fields = multipart_fields(bytes(raw), kind)
        return (
            "multipart",
            sorted(json.dumps(f, sort_keys=True) for f in fields),
        )
    if text is None:
        return ("bytes", bytes(raw))
    if kind.startswith("application/x-www-form-urlencoded"):
        return ("form", sorted(parse_qsl(text, keep_blank_values=True)))
    try:
        parsed = _drop_nulls(json.loads(text))
    except ValueError:
        return ("text", text)
    return ("empty", None) if parsed == {} else ("json", parsed)


def _render(meaning: tuple[str, Any]) -> list[str]:
    kind, value = meaning
    if kind == "json":
        return json.dumps(value, indent=2, sort_keys=True).splitlines()
    return [
        kind,
        *(str(v) for v in (value if isinstance(value, list) else [value])),
    ]


#: Top-level body fields a route reads as absent at these values (the
#: request model's defaults), by method and path.
BODY_DEFAULTS: tuple[tuple[str, re.Pattern[str], dict[str, Any]], ...] = (
    ("POST", re.compile(r"^/v1/members$"), {"member_type": "business"}),
)


def _body_defaults(request: Request) -> dict[str, Any]:
    for method, pattern, defaults in BODY_DEFAULTS:
        if request.method == method and pattern.match(request.path):
            return defaults
    return {}


def _defaults(path: str) -> dict[str, str]:
    for pattern, defaults in ROUTE_DEFAULTS:
        if pattern.match(path):
            return defaults
    return {}


def semantic_query(r1: Request, r2: Request) -> None:
    """VCR matcher: the same query, a parameter at the route's default
    standing for its absence (see the module). Order never matters."""
    defaults = _defaults(r1.path)
    recorded = {k for k, _ in r2.query}
    sent = [
        (k, v) for k, v in r1.query if k in recorded or defaults.get(k) != v
    ]
    if sent != r2.query:
        raise AssertionError(f"{r1.query} != {r2.query}")


def semantic_body(r1: Request, r2: Request) -> None:
    """VCR matcher: the two bodies mean the same thing (see the module)."""
    sent, recorded = body_meaning(r1), body_meaning(r2)
    if sent[0] == recorded[0] == "json" and isinstance(sent[1], dict):
        defaults = _body_defaults(r1)
        sent = (
            "json",
            {
                k: v
                for k, v in sent[1].items()
                if k in recorded[1] or defaults.get(k, ...) != v
            },
        )
    if sent == recorded:
        return
    # The recording holds a bare multipart postData (see the module).
    if recorded[0] == "empty" and sent[0] == "multipart":
        return
    diff = "\n".join(
        difflib.unified_diff(
            _render(recorded), _render(sent), "recorded", "sent", lineterm=""
        )
    )
    raise AssertionError(f"body differs:\n{diff}")


def scrub_request(request: Request) -> Request:
    """``before_record_request``: credential headers, and secret shapes in
    the URL and body. Runs on every request VCR compares or records."""
    request = copy.copy(request)
    request.headers = {
        k: (REDACTED if is_sensitive_header(k) else v)
        for k, v in request.headers.items()
    }
    request.uri = scrub_secrets(request.uri)
    text = _text(request.body)
    if text is not None and request.body:
        request.body = scrub_secrets(text)
    return request


def scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    """``before_record_response``: credential headers and secret shapes in
    the body, before a record run writes it."""
    response["headers"] = {
        k: ([REDACTED] * len(v) if is_sensitive_header(k) else v)
        for k, v in response["headers"].items()
    }
    body = response["body"]["string"]
    text = _text(body)
    if text is not None and body:
        response["body"]["string"] = scrub_secrets(text).encode("utf-8")
    return response
