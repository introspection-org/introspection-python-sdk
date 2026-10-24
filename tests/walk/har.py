"""A VCR.py serializer that reads and writes HAR 1.2, the shape Polly writes.

One cassette format across the SDKs (introspection-cloud
``docs/design/sdk-end-to-end-walk.md`` §9): every SDK's walk replays the same
``recording.har``, and ``scripts/route_coverage.py`` reads each SDK's with
one parser. VCR hands a serializer its own interaction dicts
(``{"request": {method, uri, body, headers}, "response": {status, headers,
body}}``); this maps them to HAR entries and back.

A HAR body is text, or base64 when it is not UTF-8 (an Arrow stream). A
multipart body is recorded as its fields (``postData.params``), as Polly
does, and read back as :data:`MULTIPART_FIELDS` JSON so the body matcher
compares fields, never a boundary.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import HTTP
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from introspection_sdk.version import VERSION

__all__ = ["MULTIPART_FIELDS", "deserialize", "multipart_fields", "serialize"]

#: The content type a recorded multipart body is read back as: its fields,
#: as a JSON list of ``{name, fileName, contentType, value}``.
MULTIPART_FIELDS = "application/vnd.walk.multipart-fields+json"

#: Response headers that describe the wire encoding, not the body the HAR
#: holds: the text is decoded and may be shorter after scrubbing.
WIRE_HEADERS = frozenset(
    {"content-encoding", "content-length", "transfer-encoding"}
)


def multipart_fields(body: bytes, content_type: str) -> list[dict[str, str]]:
    """The fields of a ``multipart/form-data`` body, in order."""
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    fields = []
    for part in message.iter_parts():
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            payload = b""
        field = {
            "name": part.get_param("name", header="content-disposition") or "",
            "value": payload.decode("utf-8", errors="replace"),
        }
        filename = part.get_filename()
        if filename is not None:
            field["fileName"] = filename
            field["contentType"] = part.get_content_type()
        fields.append(field)
    return fields


def _header_list(headers: dict[str, list[str]]) -> list[dict[str, str]]:
    return [
        {"name": name.lower(), "value": value}
        for name, values in sorted(headers.items())
        for value in values
    ]


def _header(headers: dict[str, list[str]], name: str) -> str:
    for key, values in headers.items():
        if key.lower() == name and values:
            return values[0]
    return ""


def _content(body: bytes | str | None, mime_type: str) -> dict[str, Any]:
    raw = body.encode() if isinstance(body, str) else body or b""
    content: dict[str, Any] = {"mimeType": mime_type, "size": len(raw)}
    try:
        content["text"] = raw.decode("utf-8")
    except UnicodeDecodeError:
        content["text"] = base64.b64encode(raw).decode("ascii")
        content["encoding"] = "base64"
    return content


def _post_data(request: dict[str, Any]) -> dict[str, Any] | None:
    body = request.get("body")
    raw = body.encode() if isinstance(body, str) else body
    if not raw:
        return None
    mime_type = _header(request["headers"], "content-type")
    if mime_type.startswith("multipart/form-data"):
        return {
            "mimeType": mime_type.split(";")[0],
            "params": multipart_fields(raw, mime_type),
        }
    post = _content(raw, mime_type)
    return {"mimeType": mime_type, "params": [], "text": post["text"]}


def _entry(interaction: dict[str, Any], order: int) -> dict[str, Any]:
    request, response = interaction["request"], interaction["response"]
    url = request["uri"]
    post = _post_data(request)
    req: dict[str, Any] = {
        "bodySize": len(request.get("body") or b""),
        "cookies": [],
        "headers": _header_list(request["headers"]),
        "headersSize": -1,
        "httpVersion": "HTTP/1.1",
        "method": request["method"],
        "queryString": [
            {"name": k, "value": v}
            for k, v in parse_qsl(urlsplit(url).query, keep_blank_values=True)
        ],
        "url": url,
    }
    if post is not None:
        req["postData"] = post
    content = _content(
        response["body"]["string"],
        _header(response["headers"], "content-type"),
    )
    return {
        "_id": _identity(req),
        "_order": order,
        "cache": {},
        "request": req,
        "response": {
            "bodySize": content["size"],
            "content": content,
            "cookies": [],
            "headers": _header_list(response["headers"]),
            "headersSize": -1,
            "httpVersion": "HTTP/1.1",
            "redirectURL": _header(response["headers"], "location"),
            "status": response["status"]["code"],
            "statusText": response["status"]["message"],
        },
        "startedDateTime": datetime.now(UTC).isoformat(),
        "time": 0,
        "timings": {
            "blocked": -1,
            "connect": -1,
            "dns": -1,
            "receive": 0,
            "send": 0,
            "ssl": -1,
            "wait": 0,
        },
    }


def _identity(request: dict[str, Any]) -> str:
    post = request.get("postData") or {}
    key = json.dumps(
        [
            request["method"],
            request["url"],
            post.get("text"),
            post.get("params"),
        ],
        sort_keys=True,
    )
    return hashlib.md5(key.encode()).hexdigest()


def serialize(cassette: dict[str, Any]) -> str:
    """VCR interactions to a HAR 1.2 document. ``_order`` counts identical
    requests (Polly's ordered matching); entries stay in recorded order."""
    seen: Counter[str] = Counter()
    entries = []
    for interaction in cassette["interactions"]:
        entry = _entry(interaction, 0)
        entry["_order"] = seen[entry["_id"]]
        seen[entry["_id"]] += 1
        entries.append(entry)
    har = {
        "log": {
            "_recordingName": "walk",
            "creator": {
                "comment": "vcrpy",
                "name": "introspection-python-sdk",
                "version": VERSION,
            },
            "entries": entries,
            "pages": [],
            "version": "1.2",
        }
    }
    return json.dumps(har, indent=2, ensure_ascii=False) + "\n"


def _request(req: dict[str, Any]) -> dict[str, Any]:
    headers: dict[str, list[str]] = {}
    for h in req.get("headers", []):
        headers.setdefault(h["name"], []).append(h["value"])
    post = req.get("postData") or {}
    body: bytes | None = None
    if post.get("text"):
        body = post["text"].encode("utf-8")
    elif post.get("params"):
        body = json.dumps(post["params"]).encode("utf-8")
        headers["content-type"] = [MULTIPART_FIELDS]
    return {
        "method": req["method"],
        "uri": req["url"],
        "body": body,
        "headers": {k: v[0] for k, v in headers.items()},
    }


def _response(res: dict[str, Any]) -> dict[str, Any]:
    headers: dict[str, list[str]] = {}
    for h in res.get("headers", []):
        if h["name"].lower() not in WIRE_HEADERS:
            headers.setdefault(h["name"], []).append(h["value"])
    content = res.get("content") or {}
    text = content.get("text") or ""
    body = (
        base64.b64decode(text)
        if content.get("encoding") == "base64"
        else text.encode("utf-8")
    )
    return {
        "status": {
            "code": res["status"],
            "message": res.get("statusText", ""),
        },
        "headers": headers,
        "body": {"string": body},
    }


def deserialize(document: str) -> dict[str, Any]:
    """A HAR 1.2 document to VCR interactions, in entry order."""
    entries = json.loads(document)["log"]["entries"]
    return {
        "version": 1,
        "interactions": [
            {
                "request": _request(e["request"]),
                "response": _response(e["response"]),
            }
            for e in entries
        ],
    }
