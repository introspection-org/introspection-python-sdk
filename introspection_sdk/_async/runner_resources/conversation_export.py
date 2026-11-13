"""Re-exported by :mod:`introspection_sdk.runner_resources.conversations`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from introspection_sdk._async._http import AsyncStreamedResponse
from introspection_sdk._jsonl import iter_jsonl_async
from introspection_sdk._strict_schema import decode, note_response
from introspection_sdk.schemas.genai_span import GenAiSpan

if TYPE_CHECKING:
    from introspection_sdk._async.runner_resources.conversations import (
        ConversationExportFormat,
    )

__all__ = ["INTROSPECTION_NEXT_HEADER", "AsyncConversationExport"]

#: The response header an oldest-first export answers with: the opaque
#: cursor to pass back as ``next`` to resume after the last exported item.
INTROSPECTION_NEXT_HEADER = "Introspection-Next"


class AsyncConversationExport:
    # unasync: async-only (the sync twin's docstring follows)
    """Async twin of :class:`ConversationExport`: an open conversation
    export, yielded by :meth:`AsyncConversations.open_export`.

    :attr:`next` and :attr:`nothing_newer` are known on entry, before the
    body streams; ``async for`` :meth:`iter_bytes` or :meth:`iter_spans` to
    read the body.
    """

    # unasync: end
    """An open conversation export, yielded by
    :meth:`Conversations.open_export`.

    :attr:`next` and :attr:`nothing_newer` are known on entry, before the
    body streams; iterate :meth:`iter_bytes` or :meth:`iter_spans` to read
    the body.
    """

    def __init__(
        self,
        response: AsyncStreamedResponse,
        *,
        path: str,
        format: ConversationExportFormat,
    ) -> None:
        self._response = response
        self._path = path
        self._format = format

    @property
    def next(self) -> str | None:
        """The ``Introspection-Next`` cursor, or ``None`` when not sent.

        An oldest-first export (``direction="asc"``) and any resumed one
        (``next=...``) carry it: pass it as ``next`` to the following
        :meth:`open_export` to read only what is newer. It is an opaque
        string; store it as is, never parse it or turn it into a number.
        """
        return self._response.headers.get(INTROSPECTION_NEXT_HEADER) or None

    @property
    def nothing_newer(self) -> bool:
        """``True`` when a resumed export had nothing newer (``204``).

        The body is then empty and :attr:`next` echoes the cursor that was
        sent, so the caller keeps it for the next attempt.
        """
        return self._response.status_code == 204

    @property
    def status_code(self) -> int:
        """The HTTP status: ``200`` with a body, ``204`` with nothing newer."""
        return self._response.status_code

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        """The export body's raw bytes as they arrive; none when
        :attr:`nothing_newer`."""
        if self.nothing_newer:
            return
        async for chunk in self._response.iter_bytes():
            yield chunk

    async def iter_spans(self) -> AsyncIterator[GenAiSpan]:
        """Each exported span, decoded as its JSON line arrives.

        Only for ``format="jsonl"``; the other formats are read with
        :meth:`iter_bytes`.
        """
        if self._format != "jsonl":
            raise ValueError(
                f"iter_spans() reads a jsonl export, not {self._format!r}; "
                "use iter_bytes()"
            )
        async for span in iter_jsonl_async(self.iter_bytes()):
            note_response(self._path)
            yield decode(GenAiSpan, span)
