"""VCR-style recording for Claude Agent SDK subprocess IPC.

The Python `claude-agent-sdk` package spawns the `claude` CLI as a
subprocess and talks to it over stdio, so `pytest-recording` /
`vcrpy` cannot see anything (they hook the HTTP layer). The SDK does
expose a clean seam though: ``ClaudeSDKClient(options, transport=...)``
accepts any subclass of ``claude_agent_sdk._internal.transport.Transport``.

This module wraps that seam with the same shape contributors already
know from `pytest-recording` — a per-test YAML cassette under
``tests/.../cassettes/<test_file>/<test_name>.yaml`` and a record-mode
flag (``once`` / ``new_episodes`` / ``none``) that mirrors
``vcrpy``'s semantics.

Two transports:

- :class:`RecordingTransport` wraps the real ``SubprocessCLITransport``,
  tees every outbound ``write()`` and every inbound message from
  ``read_messages()`` into a cassette in wall-clock order.
- :class:`ReplayTransport` reads from the cassette and yields the
  recorded messages without ever spawning ``claude``.

The cassette format is intentionally event-stream, not strict
request/response: the Claude CLI sometimes interleaves multiple reads
between writes and can start streaming before the corresponding
``write()`` returns. Strict pairing would force us to reorder events
and lose realism.

Usage::

    @claude_vcr_test(cassette="tests/framework/cassettes/test_x/test_y.yaml")
    async def test_y():
        async with ClaudeSDKClient(options=options) as client:
            ...

See the module docstring above for the recording-transport design
rationale, including why this is better than the JS custom-proxy
approach.
"""

from __future__ import annotations

__all__ = [
    "RecordMode",
    "RecordingTransport",
    "ReplayTransport",
    "build_claude_transport",
    "load_cassette",
    "resolve_record_mode",
    "save_cassette",
    "scrub_event",
]

import asyncio
import copy
import json
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from introspection_sdk.testing.redaction import (
    UUID_PLACEHOLDER,
    UUID_RE,
    redact_secrets,
)

try:
    from claude_agent_sdk._internal.transport import Transport
except ImportError as exc:  # pragma: no cover - dependency missing
    raise ImportError(
        "claude-agent-sdk is required for the Claude VCR helpers. "
        "Install with: pip install 'introspection-sdk[test]'"
    ) from exc


RecordMode = Literal["once", "new_episodes", "none"]
"""Mirrors `pytest-recording`'s --record-mode values.

- ``once``: record if the cassette is missing, replay if it exists.
- ``new_episodes``: always record, appending to an existing cassette.
- ``none``: replay-only; raise if the cassette is missing.
"""

_CASSETTE_VERSION = 1


@dataclass
class Event:
    """A single transport-level event in a cassette."""

    kind: Literal["write", "read"]
    data: Any

    def to_yaml(self) -> dict[str, Any]:
        return {"kind": self.kind, "data": self.data}

    @classmethod
    def from_yaml(cls, raw: dict[str, Any]) -> Event:
        return cls(kind=raw["kind"], data=raw["data"])


@dataclass
class Cassette:
    """An ordered list of transport events for one test."""

    path: Path
    events: list[Event] = field(default_factory=list)

    def append(self, event: Event) -> None:
        self.events.append(event)

    def save(self) -> None:
        payload = {
            "version": _CASSETTE_VERSION,
            "events": [e.to_yaml() for e in self.events],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump(payload, sort_keys=False))

    @classmethod
    def load(cls, path: Path) -> Cassette:
        raw = yaml.safe_load(path.read_text())
        if (
            not isinstance(raw, dict)
            or raw.get("version") != _CASSETTE_VERSION
        ):
            raise ValueError(
                f"Cassette {path} has unsupported version "
                f"{raw.get('version') if isinstance(raw, dict) else '?'}; "
                f"expected {_CASSETTE_VERSION}"
            )
        events = [Event.from_yaml(e) for e in raw.get("events", [])]
        return cls(path=path, events=events)


def load_cassette(path: Path | str) -> Cassette:
    """Load a cassette from disk. Convenience wrapper."""
    return Cassette.load(Path(path))


def save_cassette(cassette: Cassette) -> None:
    """Persist a cassette to disk. Convenience wrapper."""
    cassette.save()


# ── Scrubbing ─────────────────────────────────────────────────────

# Transport-specific ids. UUIDs and API-key/token secrets are handled
# by the shared `redaction` module.
_TOOL_USE_ID_RE = re.compile(r"toolu_[A-Za-z0-9_]{10,}")
# Control-protocol request ids look like `req_<seq>_<hex>` and are
# regenerated on every connection.
_REQUEST_ID_RE = re.compile(r'"request_id"\s*:\s*"req_\d+_[A-Za-z0-9]+"')
_REQUEST_ID_INLINE_RE = re.compile(r"req_\d+_[A-Za-z0-9]+")

_PLACEHOLDER_TOOL_USE = "toolu_REDACTED"
_PLACEHOLDER_REQUEST_ID = "req_REDACTED"

# Volatile fields the CLI stamps onto messages that don't affect
# behaviour and only add noise to diffs. Removed before persisting.
_VOLATILE_KEYS = frozenset(
    {
        "uuid",
        "parent_tool_use_id",
        "request_id",
        "duration_ms",
        "num_turns",
        "session_id",
        "result",
        "total_cost_usd",
        "usage",
    }
)


def scrub_event(event: Event, *, cwd: str | None = None) -> Event:
    """Return a copy of *event* with volatile / sensitive bits redacted.

    Redactions:
    - API keys/tokens → shared placeholders (via ``redact_secrets``)
    - UUIDs → ``00000000-...``
    - tool_use ids → ``toolu_REDACTED``
    - current working directory → ``<cwd>``
    - timestamps + cost/usage numbers stripped from result messages
    """
    cwd = cwd or os.getcwd()

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            v = redact_secrets(value)
            v = UUID_RE.sub(UUID_PLACEHOLDER, v)
            v = _TOOL_USE_ID_RE.sub(_PLACEHOLDER_TOOL_USE, v)
            v = _REQUEST_ID_INLINE_RE.sub(_PLACEHOLDER_REQUEST_ID, v)
            if cwd and cwd in v:
                v = v.replace(cwd, "<cwd>")
            return v
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k in _VOLATILE_KEYS:
                    out[k] = "<redacted>"
                else:
                    out[k] = redact(v)
            return out
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value

    return Event(kind=event.kind, data=redact(event.data))


# ── Transports ────────────────────────────────────────────────────


class RecordingTransport(Transport):
    """Wraps a real Transport; tees every write/read into a cassette.

    Events are recorded in observed (wall-clock) order. No
    request/response pairing — the Claude CLI streams asynchronously.
    """

    def __init__(self, inner: Transport, cassette: Cassette) -> None:
        self._inner = inner
        self._cassette = cassette

    async def connect(self) -> None:
        await self._inner.connect()

    async def write(self, data: str) -> None:
        self._cassette.append(scrub_event(Event(kind="write", data=data)))
        await self._inner.write(data)

    def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        return self._record_and_yield()

    async def _record_and_yield(self) -> AsyncIterator[dict[str, Any]]:
        async for msg in self._inner.read_messages():
            self._cassette.append(scrub_event(Event(kind="read", data=msg)))
            yield msg

    async def close(self) -> None:
        try:
            await self._inner.close()
        finally:
            self._cassette.save()

    def is_ready(self) -> bool:
        return self._inner.is_ready()

    async def end_input(self) -> None:
        await self._inner.end_input()


class ReplayTransport(Transport):
    """Yields cassette events without spawning the Claude CLI.

    The transport walks the recorded event stream in order. On
    ``write()``, it advances past the next recorded write (after
    skipping any unconsumed reads); on ``read_messages()``, it yields
    every consecutive ``read`` event up to the next ``write``.

    Drift handling — Claude's control protocol stamps a fresh
    ``request_id`` on every call, so the live SDK's request id will
    never match the one we recorded. The transport tracks the most
    recent outbound ``control_request`` id and rewrites inbound
    ``control_response`` ids to match it before yielding. Without this,
    the SDK times out waiting for its own request to come back.

    Write payloads are scrubbed with the same helper used on record
    and compared structurally (after JSON decode where applicable),
    not byte-for-byte. Mismatches raise ``AssertionError`` with a diff.
    """

    def __init__(self, cassette: Cassette) -> None:
        self._cassette = cassette
        self._cursor = 0
        self._ready = False
        self._closed = False
        self._last_request_id: str | None = None
        # Signalled when a write advances the cursor past a write
        # event, so the long-lived read_messages iterator can resume.
        self._write_pending = asyncio.Event()

    async def connect(self) -> None:
        self._ready = True

    async def write(self, data: str) -> None:
        # Capture the live request_id so we can rewrite the next
        # matching inbound response.
        try:
            parsed = json.loads(data.strip())
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if (
            isinstance(parsed, dict)
            and parsed.get("type") == "control_request"
        ):
            req_id = parsed.get("request_id")
            if isinstance(req_id, str):
                self._last_request_id = req_id

        scrubbed = scrub_event(Event(kind="write", data=data)).data
        # The reader task yields any pending reads first; we expect to
        # land on the next write event.
        events = self._cassette.events
        if self._cursor >= len(events):
            raise AssertionError(
                f"Cassette {self._cassette.path} exhausted on write; "
                f"unexpected: {scrubbed!r}"
            )
        expected = events[self._cursor]
        if expected.kind != "write":
            raise AssertionError(
                f"Cassette {self._cassette.path} expected {expected.kind} "
                f"at event {self._cursor}, got write({scrubbed!r})"
            )
        if not _writes_match(expected.data, scrubbed):
            raise AssertionError(
                f"Cassette {self._cassette.path} write mismatch at "
                f"event {self._cursor}.\n"
                f"  expected: {expected.data!r}\n"
                f"  actual:   {scrubbed!r}\n"
                "Re-record with --record-mode=new_episodes if the "
                "drift is intentional."
            )
        self._cursor += 1
        # Wake the reader so it emits the reads that follow this write.
        self._write_pending.set()

    def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[dict[str, Any]]:
        """Yield reads as the cursor advances over them.

        Writes block the stream until ``write()`` is called, mirroring
        the real subprocess transport where the CLI doesn't produce
        more output until the SDK has sent its next request.
        """
        events = self._cassette.events
        while not self._closed:
            if self._cursor >= len(events):
                return
            event = events[self._cursor]
            if event.kind == "read":
                self._cursor += 1
                yield self._rewrite_for_replay(event.data)
                continue
            # event.kind == "write" — wait for the SDK to call write()
            self._write_pending.clear()
            await self._write_pending.wait()

    def _rewrite_for_replay(self, data: Any) -> Any:
        """Stamp the live request_id onto recorded control_responses."""
        if (
            self._last_request_id
            and isinstance(data, dict)
            and data.get("type") == "control_response"
        ):
            rewritten = copy.deepcopy(data)
            response = rewritten.get("response")
            if isinstance(response, dict):
                response["request_id"] = self._last_request_id
            return rewritten
        return data

    async def close(self) -> None:
        self._closed = True
        self._ready = False
        self._write_pending.set()  # unblock the reader so it can exit

    def is_ready(self) -> bool:
        return self._ready

    async def end_input(self) -> None:
        pass


def _writes_match(expected: Any, actual: Any) -> bool:
    """Compare two write payloads, decoding JSON when possible.

    JSON-decoding both sides means we tolerate insignificant
    whitespace + key-ordering differences across SDK versions while
    still catching real shape changes.
    """
    if expected == actual:
        return True
    if not (isinstance(expected, str) and isinstance(actual, str)):
        return False
    try:
        return json.loads(expected.strip()) == json.loads(actual.strip())
    except (json.JSONDecodeError, ValueError):
        return False


# ── Mode resolution ───────────────────────────────────────────────


def resolve_record_mode(
    cassette_path: Path,
    requested: RecordMode | None = None,
) -> Literal["record", "replay"]:
    """Decide whether to record or replay for *cassette_path*.

    Honours the ``--record-mode`` flag from ``pytest-recording`` by
    checking ``request.config.option.record_mode`` upstream; callers
    can pass the resolved value here as *requested*.
    """
    mode = requested or "once"
    if mode == "new_episodes":
        return "record"
    if mode == "none":
        if not cassette_path.exists():
            raise FileNotFoundError(
                f"Cassette {cassette_path} not found and record-mode is "
                "'none'; re-run with --record-mode=once to record."
            )
        return "replay"
    # "once"
    return "replay" if cassette_path.exists() else "record"


async def _empty_prompt_stream() -> AsyncIterator[dict[str, Any]]:
    """Async iterator that never yields. Used as a placeholder prompt."""
    if False:
        yield {}  # pragma: no cover


def build_claude_transport(
    options: Any,
    cassette_path: Path | str,
    *,
    record_mode: RecordMode | None = None,
) -> Transport:
    """Build a recording or replaying Transport based on cassette presence.

    Args:
        options: The ``ClaudeAgentOptions`` that will be passed to
            ``ClaudeSDKClient``. Forwarded to ``SubprocessCLITransport``
            when recording.
        cassette_path: Where the cassette lives (or should be written
            to). The path is auto-created on first record.
        record_mode: Optional override; mirrors ``pytest-recording``
            semantics. Defaults to ``"once"``.

    Returns:
        Either a :class:`RecordingTransport` wrapping a fresh
        ``SubprocessCLITransport`` (when recording) or a
        :class:`ReplayTransport` reading from disk.
    """
    cassette_path = Path(cassette_path)
    mode = resolve_record_mode(cassette_path, record_mode)
    if mode == "replay":
        return ReplayTransport(cassette=load_cassette(cassette_path))

    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )

    inner = SubprocessCLITransport(
        prompt=_empty_prompt_stream(), options=options
    )
    cassette = Cassette(path=cassette_path)
    return RecordingTransport(inner=inner, cassette=cassette)
