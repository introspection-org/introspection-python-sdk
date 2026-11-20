"""SSE line splitting: only CRLF, LF and CR end a line.

``httpx``'s line iterator splits where ``str.splitlines`` does, so a
``data:`` line whose JSON string holds U+2028 (or ``\\x0b`` ... ``\\x85``)
used to arrive cut and fail ``json.loads``. These tests drive
``stream_sse_lines`` and the resumable run stream through the in-process
``httpx.MockTransport`` (see ``conftest.FakeAPI``), with bodies delivered
in chosen chunks so terminators fall on chunk boundaries.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator

import httpx2 as httpx
import pytest

from introspection_sdk._sse_lines import SseLineSplitter
from introspection_sdk.runner_resources.tasks import AsyncTasks, Tasks
from introspection_sdk.schemas.agui import (
    AGUIStreamEvent,
    TextMessageContentEvent,
)
from introspection_sdk.streaming import parse_ag_ui_events

from .conftest import TASK_ID, FakeAPI

RUN_ID = "run-1"
STREAM_PATH = f"/v1/tasks/{TASK_ID}/runs/{RUN_ID}/stream"

# Every character str.splitlines treats as a line end that SSE does not.
SPLITLINES_ONLY = [
    "\x0b",
    "\x0c",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    " ",
    " ",
]


class ChunkedStream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A response body delivered as exactly these chunks, sync or async."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def _serve(fake_api: FakeAPI, path: str, chunks: list[bytes]) -> None:
    fake_api.add_handler(
        "GET",
        path,
        lambda _request: httpx.Response(200, stream=ChunkedStream(chunks)),
    )


def _frame(delta: str, seq: str = "1") -> str:
    payload = json.dumps(
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": delta},
        ensure_ascii=False,
    )
    return f"id: {seq}\nevent: ag_ui\ndata: {payload}\n\n"


def _deltas(events: list[AGUIStreamEvent]) -> list[str]:
    return [e.delta for e in events if isinstance(e, TextMessageContentEvent)]


FINISH = (
    'id: c-0\nevent: ag_ui\ndata: {"type":"RUN_FINISHED",'
    '"threadId":"t","runId":"run-1"}\n\n'
)


# --- the splitter ------------------------------------------------------


def _split(chunks: list[bytes]) -> list[str]:
    splitter = SseLineSplitter()
    lines = [line for chunk in chunks for line in splitter.feed(chunk)]
    return lines + splitter.flush()


@pytest.mark.parametrize("char", SPLITLINES_ONLY)
def test_splitlines_only_characters_stay_inside_the_line(char: str):
    line = f'data: {{"a":"x{char}y"}}'
    assert _split([f"{line}\n\n".encode()]) == [line, ""]


@pytest.mark.parametrize("ending", ["\r\n", "\n", "\r"])
def test_each_spec_line_ending(ending: str):
    body = ending.join(["event: a", "data: 1", "", "data: 2", ""])
    assert _split([body.encode()]) == ["event: a", "data: 1", "", "data: 2"]


def test_mixed_line_endings_in_one_chunk():
    assert _split([b"a\r\nb\rc\n\r\n"]) == ["a", "b", "c", ""]


def test_crlf_split_across_chunks_is_one_line_end():
    assert _split([b"data: 1\r", b"\ndata: 2\r", b"\n\r", b"\n"]) == [
        "data: 1",
        "data: 2",
        "",
    ]


def test_cr_at_chunk_end_then_other_text_is_a_line_end():
    assert _split([b"a\r", b"b\r", b"\r", b"c"]) == ["a", "b", "", "c"]


def test_empty_chunk_keeps_a_pending_cr():
    assert _split([b"a\r", b"", b"\nb\n"]) == ["a", "b"]


def test_line_split_across_many_chunks_and_inside_a_character():
    body = 'data: {"a":"é ü"}\n'.encode()
    chunks = [body[i : i + 1] for i in range(len(body))]
    assert _split(chunks) == ['data: {"a":"é ü"}']


def test_last_unterminated_line_is_flushed_at_eof():
    splitter = SseLineSplitter()
    assert splitter.feed(b"data: 1\ndata: 2") == ["data: 1"]
    assert splitter.flush() == ["data: 2"]
    assert splitter.flush() == []


def test_a_leading_byte_order_mark_is_dropped_once():
    assert _split(["﻿data: 1\n﻿x\n".encode()]) == [
        "data: 1",
        "﻿x",
    ]


# --- stream_sse_lines over the transport --------------------------------


@pytest.mark.parametrize("char", SPLITLINES_ONLY)
def test_stream_sse_lines_frames_parse_intact_sync(
    fake_api: FakeAPI, char: str
):
    _serve(fake_api, "/v1/stream", [_frame(f"x{char}y").encode()])
    http = fake_api.client()
    events = list(parse_ag_ui_events(http.stream_sse_lines("/v1/stream")))
    assert _deltas(events) == [f"x{char}y"]


@pytest.mark.parametrize("char", SPLITLINES_ONLY)
async def test_stream_sse_lines_frames_parse_intact_async(
    fake_api: FakeAPI, char: str
):
    _serve(fake_api, "/v1/stream", [_frame(f"x{char}y").encode()])
    http = fake_api.async_client()
    lines = [line async for line in http.stream_sse_lines("/v1/stream")]
    events = list(parse_ag_ui_events(lines))
    assert _deltas(events) == [f"x{char}y"]


CHUNKED_CRLF = [
    b"event: ag_ui\r",
    b'\ndata: {"type":"TEXT_MESSAGE_CONTENT",\r\n',
    b'data: "messageId":"m",\r',
    b'data: "delta":"a\xe2\x80',
    b'\xa8b"}\r',
    b"\n\r",
    b"\nevent: heartbeat\rdata: {}\r\r",
    b"data: tail",
]
CHUNKED_CRLF_LINES = [
    "event: ag_ui",
    'data: {"type":"TEXT_MESSAGE_CONTENT",',
    'data: "messageId":"m",',
    'data: "delta":"a b"}',
    "",
    "event: heartbeat",
    "data: {}",
    "",
    "data: tail",
]


def test_stream_sse_lines_chunk_boundaries_and_multiline_data_sync(
    fake_api: FakeAPI,
):
    _serve(fake_api, "/v1/stream", CHUNKED_CRLF)
    http = fake_api.client()
    lines = list(http.stream_sse_lines("/v1/stream"))
    assert lines == CHUNKED_CRLF_LINES
    events = list(parse_ag_ui_events(lines))
    assert _deltas(events) == ["a b"]


async def test_stream_sse_lines_chunk_boundaries_and_multiline_data_async(
    fake_api: FakeAPI,
):
    _serve(fake_api, "/v1/stream", CHUNKED_CRLF)
    http = fake_api.async_client()
    lines = [line async for line in http.stream_sse_lines("/v1/stream")]
    assert lines == CHUNKED_CRLF_LINES


# --- the resumable run stream end to end --------------------------------


def _run_stream_chunks() -> list[bytes]:
    body = "".join(
        _frame(f"{i}{char}", seq=str(i + 1))
        for i, char in enumerate(SPLITLINES_ONLY)
    )
    raw = (body + FINISH).encode()
    # Cut into 7-byte chunks so terminators and characters straddle chunks.
    return [raw[i : i + 7] for i in range(0, len(raw), 7)]


EXPECTED_DELTAS = [f"{i}{char}" for i, char in enumerate(SPLITLINES_ONLY)]


def test_resumable_stream_keeps_splitlines_characters_sync(fake_api: FakeAPI):
    _serve(fake_api, STREAM_PATH, _run_stream_chunks())
    tasks = Tasks(fake_api.client())

    events = list(tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001))

    assert _deltas(events) == EXPECTED_DELTAS
    assert events[-1].type == "RUN_FINISHED"


async def test_resumable_stream_keeps_splitlines_characters_async(
    fake_api: FakeAPI,
):
    _serve(fake_api, STREAM_PATH, _run_stream_chunks())
    tasks = AsyncTasks(fake_api.async_client())

    events = [
        e async for e in tasks.runs.stream(TASK_ID, RUN_ID, backoff=0.001)
    ]

    assert _deltas(events) == EXPECTED_DELTAS
    assert events[-1].type == "RUN_FINISHED"
