"""Deferred responses (`#deferred-responses`): the `202` pending answer, its
`AAuth-Requirement` header and `Retry-After`."""

from collections.abc import Mapping

import http_sfv

from introspection_aauth.protocol.answer import Answer
from introspection_aauth.protocol.wire import Pending


def requirement(
    name: str, *, url: str | None = None, code: str | None = None
) -> str:
    """An `AAuth-Requirement` header (`#requirement-values`): an RFC 9651
    Dictionary whose `requirement` carries its parameters, strings escaped."""
    item = http_sfv.Item(http_sfv.Token(name))
    if url is not None:
        item.params["url"] = url
    if code is not None:
        item.params["code"] = code
    header = http_sfv.Dictionary()
    header["requirement"] = item
    return str(header)


def requirement_name(header: str) -> str | None:
    """The `requirement` an `AAuth-Requirement` header names, or None when
    it is not an RFC 9651 Dictionary that names one."""
    parsed = http_sfv.Dictionary()
    try:
        parsed.parse(header.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None
    item = parsed.get("requirement")
    return str(item.value) if item is not None else None


def retry_after(headers: Mapping[str, str]) -> int | None:
    """`Retry-After` in seconds, when it is a number."""
    try:
        return max(int(headers.get("retry-after", "")), 0)
    except ValueError:
        return None


def pending(
    location: str, retry_after: int, requirement: str | None = None
) -> Answer:
    """`202`: poll `location` (`#deferred-responses`)."""
    return Answer(
        202,
        Pending(),
        {
            "Location": location,
            "Retry-After": str(retry_after),
            "Cache-Control": "no-store",
            "AAuth-Requirement": requirement or APPROVAL_REQUIREMENT,
        },
    )


APPROVAL_REQUIREMENT = "requirement=approval"
