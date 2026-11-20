"""Split a server-sent event stream into lines the way the SSE spec does.

The spec ends a line only at CRLF, LF or CR. ``httpx``'s ``iter_lines`` uses
``str.splitlines``, which also splits at ``\\x0b``, ``\\x0c``, ``\\x1c``,
``\\x1d``, ``\\x1e``, ``\\x85``, U+2028 and U+2029, so a ``data:`` line whose
JSON string holds one of them arrives cut in two and fails to parse.
:class:`SseLineSplitter` works on the raw bytes: CR and LF are single bytes in
UTF-8 and never part of a multi-byte character, so a line is cut only at a
real terminator and decoded whole.
"""

from __future__ import annotations

import re

__all__ = ["SseLineSplitter"]

LINE_END = re.compile(rb"\r\n|\r|\n")
BOM = "﻿"


class SseLineSplitter:
    """Incremental SSE line splitter, safe across chunk boundaries.

    Feed body chunks to :meth:`feed`, which returns the lines they complete,
    and call :meth:`flush` at EOF for the last line that had no terminator. A
    CR that ends one chunk ends its line at once; an LF that opens the next
    chunk is then the second half of that CRLF, not an empty line.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._skip_lf = False
        self._first = True

    def feed(self, chunk: bytes) -> list[str]:
        if not chunk:
            return []
        if self._skip_lf and chunk.startswith(b"\n"):
            chunk = chunk[1:]
        self._skip_lf = False
        # The kept remainder holds no terminator, so scan only the new bytes.
        scan_from = len(self._buf)
        self._buf += chunk
        lines: list[str] = []
        start = 0
        for match in LINE_END.finditer(self._buf, scan_from):
            lines.append(self._decode(self._buf[start : match.start()]))
            start = match.end()
        self._skip_lf = self._buf.endswith(b"\r")
        del self._buf[:start]
        return lines

    def flush(self) -> list[str]:
        """Return the unterminated last line, if any, and reset."""
        if not self._buf:
            return []
        line = self._decode(self._buf)
        self._buf.clear()
        return [line]

    def _decode(self, raw: bytes | bytearray) -> str:
        line = raw.decode("utf-8", errors="replace")
        if self._first:
            # The spec drops one UTF-8 byte order mark at the stream start.
            self._first = False
            line = line.removeprefix(BOM)
        return line
