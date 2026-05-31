"""Tests for ``runner.files`` (:mod:`introspection_sdk.runner_resources.files`)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from introspection_sdk.runner_resources.files import (
    Files,
    _materialise_upload,
)
from introspection_sdk.schemas.files import FileType

from .conftest import FILE_ID, FakeAPI, file_payload, paginated


def _files(fake_api: FakeAPI) -> Files:
    return Files(fake_api.client())


# --- _materialise_upload (pure helper) ------------------------------


def test_materialise_path_guesses_name_and_type(tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text("{}")
    name, body, ct = _materialise_upload(p, None, None)
    assert name == "data.json"
    assert ct == "application/json"
    assert not isinstance(body, bytes)
    body.close()


def test_materialise_bytes_requires_name():
    with pytest.raises(ValueError, match="name` is required"):
        _materialise_upload(b"abc", None, None)


def test_materialise_bytes_with_explicit_content_type():
    name, body, ct = _materialise_upload(b"abc", "x.bin", "text/plain")
    assert (name, body, ct) == ("x.bin", b"abc", "text/plain")


def test_materialise_filelike_requires_name():
    with pytest.raises(ValueError, match="name` is required"):
        _materialise_upload(io.BytesIO(b"x"), None, None)


def test_materialise_filelike_guesses_octet_stream_default():
    name, body, ct = _materialise_upload(io.BytesIO(b"x"), "blob", None)
    assert name == "blob"
    assert ct == "application/octet-stream"


# --- Files CRUD ------------------------------------------------------


def test_list_with_file_type_enum(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    page = _files(fake_api).list(file_type=FileType.UPLOAD)
    assert str(page.records[0].id) == FILE_ID
    assert fake_api.last_request.params.get("file_type") == "upload"


def test_iter(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/files", json_body=paginated([file_payload()]))
    assert len(list(_files(fake_api).iter())) == 1


def test_upload_sends_multipart(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/files", json_body=file_payload())
    f = _files(fake_api).upload(
        file=b"hello", name="greeting.txt", file_type="upload"
    )
    assert str(f.id) == FILE_ID
    sent = fake_api.last_request
    assert "multipart/form-data" in sent.headers["content-type"]
    assert b"greeting.txt" in sent.content


def test_create_text_sends_json(fake_api: FakeAPI):
    fake_api.add("POST", "/v1/files", json_body=file_payload())
    _files(fake_api).create_text(name="notes.md", content="# hi")
    body = fake_api.last_request.json()
    assert body["name"] == "notes.md"
    assert body["mime_type"] == "text/markdown"


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
    assert len(list(_files(fake_api).versions.iter(FILE_ID))) == 1


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
