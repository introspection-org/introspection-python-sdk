"""AAuth errors, answered as `application/problem+json` (`#error-responses`)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict


class Problem(BaseModel):
    """`application/problem+json` (`#error-responses`)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    error: str
    detail: str | None = None


@dataclass(frozen=True)
class Answer:
    """What a protocol request is answered with, for any web framework: its
    status, its body, serialised with members that are None left out, and
    its headers."""

    status: int
    body: BaseModel
    headers: dict[str, str] = field(default_factory=dict)

    def content(self) -> bytes:
        return self.body.model_dump_json(exclude_none=True).encode()


class AAuthError(Exception):
    """A refusal: `status`, an AAuth `error` code and a `detail`."""

    def __init__(
        self,
        status: int,
        error: str,
        detail: str = "",
        headers: Mapping[str, str] | None = None,
    ):
        super().__init__(detail or error)
        self.status = status
        self.error = error
        self.detail = detail
        self.headers = dict(headers or {})

    def answer(self) -> Answer:
        return Answer(
            self.status,
            Problem(error=self.error, detail=self.detail or None),
            {"Content-Type": "application/problem+json", **self.headers},
        )


class VerificationError(Exception):
    """A token or signature that failed a check, with the AAuth code for it.

    Callers decide the status: the same failure is a `401` on an agent's
    request and a `400` on a token it presents.
    """

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
