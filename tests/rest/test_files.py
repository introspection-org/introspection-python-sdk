"""Tests for ``runner.files`` (:mod:`introspection_sdk.runner_resources.files`)."""

from __future__ import annotations

import io
import json
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import pytest

from introspection_sdk._errors import ConflictError
from introspection_sdk.runner_resources.files import (
    Files,
    _materialise_upload,
)
from introspection_sdk.schemas.files import FileType

from .conftest import FILE_ID, FakeAPI, file_payload, paginated


def _files(fake_api: FakeAPI) -> Files:
    return Files(fake_api.client())


def _form_fields(content_type: str, content: bytes) -> list[tuple[str, str]]:
    """Return the non-file ``(name, value)`` multipart fields, in order."""
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + content
    )
    return [
        (
            str(part.get_param("name", header="content-disposition")),
            str(part.get_content()),
        )
        for part in message.iter_parts()
        if part.get_filename() is None
    ]


# --- _materialise_upload (pure helper) ------------------------------


def test_materialise_path_guesses_name_and_type(tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text("{}")
    with _materialise_upload(p, None, None) as (name, body, ct):
        assert name == "data.json"
        assert ct == "application/json"
        assert not isinstance(body, bytes)
        handle = body
    # The handle it opened is closed on the way out; it used to be handed to
    # httpx and leaked, one descriptor per upload.
    assert handle.closed


def test_materialise_bytes_requires_name():
    with pytest.raises(ValueError, match="name` is required"):
        with _materialise_upload(b"abc", None, None):
            pass


def test_materialise_bytes_with_explicit_content_type():
    with _materialise_upload(b"abc", "x.bin", "text/plain") as triple:
        assert triple == ("x.bin", b"abc", "text/plain")


def test_materialise_filelike_requires_name():
    with pytest.raises(ValueError, match="name` is required"):
        with _materialise_upload(io.BytesIO(b"x"), None, None):
            pass


def test_materialise_filelike_is_not_closed_for_the_caller(tmp_path: Path):
    # The SDK did not open it, so it does not own it.
    stream = io.BytesIO(b"x")
    with _materialise_upload(stream, "blob", None) as (name, body, ct):
        assert name == "blob"
        assert ct == "application/octet-stream"
        assert body is stream
    assert not stream.closed


# --- Files CRUD ------------------------------------------------------


def test_list_with_file_type_enum(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    page = _files(fake_api).list(file_type=FileType.UPLOAD)
    assert str(page.records[0].id) == FILE_ID
    assert fake_api.last_request.params.get("file_type") == "upload"


def test_iter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    assert len(list(_files(fake_api).list())) == 1


def test_upload_sends_multipart(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/files", json_body=file_payload())
    f = _files(fake_api).upload(
        file=b"hello", name="greeting.txt", file_type="upload"
    )
    assert str(f.id) == FILE_ID
    sent = fake_api.last_request
    assert "multipart/form-data" in sent.headers["content-type"]
    assert b"greeting.txt" in sent.content


def test_upload_sends_tags_and_metadata_as_form_fields(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/files", json_body=file_payload())
    _files(fake_api).upload(
        file=b"hello",
        name="greeting.txt",
        metadata={"source": "crm"},
        tags=["customer:acme", "tier:gold"],
    )
    sent = fake_api.last_request
    fields = _form_fields(sent.headers["content-type"], sent.content)

    # One `tags` field per tag, order preserved; metadata as a JSON string.
    assert [v for k, v in fields if k == "tags"] == [
        "customer:acme",
        "tier:gold",
    ]
    (metadata,) = [v for k, v in fields if k == "metadata"]
    assert json.loads(metadata) == {"source": "crm"}


def test_upload_omits_tags_and_metadata_when_unset(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/files", json_body=file_payload())
    _files(fake_api).upload(file=b"hello", name="greeting.txt")
    sent = fake_api.last_request
    fields = _form_fields(sent.headers["content-type"], sent.content)

    assert [k for k, _ in fields] == ["name", "file_type"]


def test_create_text_sends_json(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/files", json_body=file_payload())
    _files(fake_api).create_text(name="notes.md", content="# hi")

    # Unset tags and metadata stay off the wire.
    assert fake_api.last_request.json() == {
        "name": "notes.md",
        "content": "# hi",
        "mime_type": "text/markdown",
    }


def test_create_text_sends_tags_and_metadata(fake_api: FakeAPI):
    fake_api.add(
        "POST", "/v1/files", json_body=file_payload(tags=["customer:acme"])
    )
    f = _files(fake_api).create_text(
        name="notes.md",
        content="# hi",
        metadata={"source": "crm"},
        tags=["customer:acme"],
    )
    body = fake_api.last_request.json()

    assert body["tags"] == ["customer:acme"]
    assert body["metadata"] == {"source": "crm"}
    assert f.tags == ["customer:acme"]


def test_create_text_surfaces_a_tag_conflict(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        "/v1/files",
        status=409,
        json_body={"detail": "tags differ from the existing file"},
    )
    # A new version keeps the file's tags; a different set is refused.
    with pytest.raises(ConflictError) as excinfo:
        _files(fake_api).create_text(
            name="notes.md", content="# v2", tags=["customer:other"]
        )
    assert excinfo.value.status_code == 409


def test_get(fake_api: FakeAPI):
    fake_api.add("GET", f"/v1/files/{FILE_ID}", json_body=file_payload())
    assert _files(fake_api).get(FILE_ID).name == "input.jsonl"


def test_update_excludes_none(fake_api: FakeAPI):
    fake_api.add(
        "PATCH",
        f"/v1/files/{FILE_ID}",
        json_body=file_payload(name="renamed.jsonl"),
    )
    f = _files(fake_api).update(FILE_ID, name="renamed.jsonl")
    assert f.name == "renamed.jsonl"
    assert fake_api.last_request.json() == {"name": "renamed.jsonl"}


def test_delete(fake_api: FakeAPI):
    fake_api.add("DELETE", f"/v1/files/{FILE_ID}", status=204)
    assert _files(fake_api).delete(FILE_ID) is None


def test_download_returns_bytes(fake_api: FakeAPI):
    fake_api.add("GET", f"/v1/files/{FILE_ID}/content", content=b"binary-data")
    assert _files(fake_api).download(FILE_ID) == b"binary-data"


def test_download_stream_yields_bytes(fake_api: FakeAPI):
    fake_api.add("GET", f"/v1/files/{FILE_ID}/content", content=b"streamed")
    chunks = b"".join(_files(fake_api).download_stream(FILE_ID))
    assert chunks == b"streamed"


# --- File versions ---------------------------------------------------


def test_versions_list(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/files/{FILE_ID}/versions",
        json_body=paginated([file_payload(version=2)]),
    )
    page = _files(fake_api).versions.list(FILE_ID)
    assert page.records[0].version == 2


def test_versions_iter(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/files/{FILE_ID}/versions",
        json_body=paginated([file_payload()]),
    )
    assert len(list(_files(fake_api).versions.list(FILE_ID))) == 1


def test_versions_get(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/files/{FILE_ID}/versions/v2",
        json_body=file_payload(version=2),
    )
    assert _files(fake_api).versions.get(FILE_ID, "v2").version == 2


def test_versions_create_uploads(fake_api: FakeAPI):
    fake_api.add(
        "POST",
        f"/v1/files/{FILE_ID}/versions",
        json_body=file_payload(version=2),
    )
    f = _files(fake_api).versions.create(
        FILE_ID, file=b"new", name="v2.bin", file_type=FileType.UPLOAD
    )
    assert f.version == 2
    assert (
        "multipart/form-data" in fake_api.last_request.headers["content-type"]
    )


def test_list_sends_the_tag_filter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    Files(fake_api.client()).list(tag="customer:acme").page()

    assert fake_api.last_request.params["tag"] == "customer:acme"


def test_list_sends_metadata_as_repeated_pairs(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    Files(fake_api.client()).list(
        metadata={"source": "crm", "ref": "a:b"}, tag="customer:acme"
    ).page()

    req = fake_api.last_request
    assert req.url.params.get_list("metadata") == ["source:crm", "ref:a:b"]
    assert req.params["tag"] == "customer:acme"


def test_list_omits_empty_metadata_filter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    Files(fake_api.client()).list(metadata={}).page()

    assert "metadata" not in fake_api.last_request.url.params


def test_update_sends_tags(fake_api: FakeAPI):
    fake_api.add("PATCH", f"/v1/files/{FILE_ID}", json_body=file_payload())
    Files(fake_api.client()).update(FILE_ID, tags=["customer:acme"])

    assert fake_api.last_request.json()["tags"] == ["customer:acme"]


def test_update_clears_tags_with_an_explicit_empty_list(fake_api: FakeAPI):
    fake_api.add("PATCH", f"/v1/files/{FILE_ID}", json_body=file_payload())
    Files(fake_api.client()).update(FILE_ID, tags=[])

    # Replaces wholesale, so [] must reach the wire rather than be dropped
    # as an empty value the way an omitted tag list is.
    assert fake_api.last_request.json() == {"tags": []}


def test_reads_tags_back_off_a_file(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        f"/v1/files/{FILE_ID}",
        json_body=file_payload(tags=["customer:acme"]),
    )

    assert Files(fake_api.client()).get(FILE_ID).tags == ["customer:acme"]
