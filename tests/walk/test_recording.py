"""The walk's recorder: HAR in and out, scrubbing, and matching.

The walk itself only replays here (no stack), so these drive the record
path over an in-process transport: what a live record run writes is
scrubbed, reads back as HAR, and replays identical requests in recorded
order, and a request the SDK changed fails naming the difference.
"""

from __future__ import annotations

import base64
import copy
import io
import json
from pathlib import Path

import httpx2 as httpx
import pytest
import vcr.serialize
from vcr.errors import CannotOverwriteExistingCassetteException
from vcr.record_mode import RecordMode
from vcr.request import Request

from introspection_sdk import IntrospectionClient
from introspection_sdk.testing.redaction import (
    is_sensitive_header,
    scrub_secrets,
)

from . import har
from .conftest import HAR, walk_vcr
from .matching import body_meaning, semantic_body, semantic_query
from .stable import stable
from .support import has_complete_recording


def _b64(part: bytes) -> str:
    return base64.urlsafe_b64encode(part).rstrip(b"=").decode()


#: A JWT-shaped token, built here so no token sits in the source.
JWT = ".".join(
    _b64(part)
    for part in (b'{"alg":"HS256"}', b'{"sub":"walk-user"}', b"sig-value-x")
)
SECRET = "intro_sec_abcdefghijklmnopqrstuvwxyz"


def _handler(request: httpx.Request) -> httpx.Response:
    count = int(request.headers.get("x-count", "0"))
    return httpx.Response(
        200,
        json={
            "id": "p",
            "description": f"read {count}",
            "access_token": JWT,
            "secret": SECRET,
        },
        headers={"set-cookie": "intro_cp_session=abc"},
    )


def _client() -> IntrospectionClient:
    return IntrospectionClient(
        token=JWT,
        base_api_url="http://cp.test",
        dp_url="http://dp.test",
        transport=httpx.MockTransport(_handler),
    )


def test_the_recording_reaches_the_teardown() -> None:
    assert has_complete_recording(HAR)


def test_har_round_trips_through_vcr() -> None:
    text = HAR.read_text()
    requests, responses = vcr.serialize.deserialize(text, har)
    # VCR's serialize decodes the bodies it is handed in place.
    again = vcr.serialize.serialize(
        {"requests": requests, "responses": copy.deepcopy(responses)}, har
    )
    requests2, responses2 = vcr.serialize.deserialize(again, har)
    assert requests
    assert len(requests2) == len(requests)
    for a, b in zip(requests, requests2, strict=True):
        assert (a.method, a.uri, body_meaning(a)) == (
            b.method,
            b.uri,
            body_meaning(b),
        )
    for a, b in zip(responses, responses2, strict=True):
        assert a["status"] == b["status"]
        assert a["body"]["string"] == b["body"]["string"]
    entries = json.loads(again)["log"]["entries"]
    # An Arrow body is not UTF-8 and goes back out as base64.
    assert any(
        e["response"]["content"].get("encoding") == "base64" for e in entries
    )
    # `_order` counts identical requests, as Polly's does.
    orders = {
        e["_order"] for e in entries if "/v1/projects/" in e["request"]["url"]
    }
    assert orders >= {0, 1}


def test_a_record_run_scrubs_and_replays_in_order(
    pytestconfig: pytest.Config, tmp_path: Path
) -> None:
    recorder = walk_vcr(pytestconfig, RecordMode.ALL, tmp_path)
    with recorder.use_cassette("recording.har"):
        client = _client()
        for count in (1, 2):
            client._http.request(
                "GET", "/v1/projects/p", headers={"x-count": str(count)}
            )
        client._http.request(
            "POST",
            "/v1/files/f/versions",
            files={"file": ("a.txt", io.BytesIO(b"v2"), "text/plain")},
        )
        client._http.request(
            "POST", "/v1/credentials", json={"secret": "plain", "name": None}
        )
    document = (tmp_path / "recording.har").read_text()
    assert JWT not in document and SECRET not in document
    assert "intro_cp_session=abc" not in document
    entries = json.loads(document)["log"]["entries"]
    headers = {h["name"]: h["value"] for h in entries[0]["request"]["headers"]}
    assert headers["authorization"] == "REDACTED"
    assert [e["_order"] for e in entries[:2]] == [0, 1]
    upload = entries[2]["request"]["postData"]
    assert upload["mimeType"] == "multipart/form-data"
    assert upload["params"][0] == {
        "name": "file",
        "value": "v2",
        "fileName": "a.txt",
        "contentType": "text/plain",
    }
    assert "REDACTED_SECRET" in entries[3]["request"]["postData"]["text"]

    replay = walk_vcr(pytestconfig, RecordMode.NONE, tmp_path)
    with replay.use_cassette("recording.har", allow_playback_repeats=False):
        client = _client()
        # Identical requests answer in recorded order, once each; the body
        # matches though the secret was scrubbed and `name: null` dropped.
        reads = [client._http.request("GET", "/v1/projects/p") for _ in "ab"]
        assert [r["description"] for r in reads] == ["read 1", "read 2"]
        client._http.request(
            "POST",
            "/v1/files/f/versions",
            files={"file": ("a.txt", io.BytesIO(b"v2"), "text/plain")},
        )
        client._http.request(
            "POST", "/v1/credentials", json={"secret": "plain"}
        )
        with pytest.raises(CannotOverwriteExistingCassetteException):
            client._http.request("GET", "/v1/projects/p")


def _request(body: str, content_type: str = "application/json") -> Request:
    return Request(
        "POST", "http://x.test/v1/a", body, {"content-type": content_type}
    )


def test_a_changed_body_fails_with_its_diff() -> None:
    semantic_body(_request('{"a": 1, "b": [1]}'), _request('{"b":[1],"a":1}'))
    semantic_body(_request("{}"), _request(""))
    with pytest.raises(AssertionError, match=r'(?s)-  "a": 1.*\+  "a": 2'):
        semantic_body(_request('{"a": 2}'), _request('{"a": 1}'))
    form = "application/x-www-form-urlencoded"
    semantic_body(_request("b=2&a=1", form), _request("a=1&b=2", form))
    # A body the recording holds none of matches only a multipart one.
    with pytest.raises(AssertionError):
        semantic_body(_request('{"a": 1}'), _request(""))


def test_a_route_default_stands_for_its_absence() -> None:
    def get(url: str) -> Request:
        return Request("GET", url, None, {})

    semantic_query(
        get("http://x.test/v1/tasks?limit=100&include_total=false"),
        get("http://x.test/v1/tasks"),
    )
    with pytest.raises(AssertionError):
        semantic_query(
            get("http://x.test/v1/tasks?limit=50"),
            get("http://x.test/v1/tasks"),
        )
    # A route with no listed default gets no allowance.
    with pytest.raises(AssertionError):
        semantic_query(
            get("http://x.test/v1/judges?limit=100"),
            get("http://x.test/v1/judges"),
        )


def test_redaction_matches_the_js_list() -> None:
    assert scrub_secrets(f"Bearer {JWT}") == "Bearer REDACTED_JWT"
    assert scrub_secrets(SECRET) == "REDACTED_INTROSPECTION_KEY"
    assert (
        scrub_secrets("client_id=a&client_secret=s3cret&x=1")
        == "client_id=a&client_secret=REDACTED_SECRET&x=1"
    )
    assert (
        scrub_secrets('{"api_key": "k"}') == '{"api_key": "REDACTED_SECRET"}'
    )
    assert is_sensitive_header("X-Session-Id")
    assert not is_sensitive_header("content-type")


def test_stable_names_what_it_replaces() -> None:
    assert stable(
        {
            "id": "01a16a8d-5e8e-76ca-88f7-401338c97e70",
            "created_at": "2026-10-23T20:56:54.501Z",
            "git_commit_sha": "543b8db50a839029b03d7ca7957884d806df646c",
            "token": "opaque",
            "url": "http://localhost:8000/x",
            "mcp_server_id": "hello-mcp",
            "invocation_id": "inv_123",
            "duration_ms": 12.5,
            "has_errors": True,
            "path": "a/01a16a8d-5e8e-76ca-88f7-401338c97e70/b.txt",
        }
    ) == {
        "id": "[uuid]",
        "created_at": "[timestamp]",
        "git_commit_sha": "[sha]",
        "token": "[redacted]",
        "url": "[url]",
        "mcp_server_id": "hello-mcp",
        "invocation_id": "[id]",
        "duration_ms": "[number]",
        "has_errors": True,
        "path": "a/[uuid]/b.txt",
    }
