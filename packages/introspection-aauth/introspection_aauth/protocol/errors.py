"""AAuth errors, answered as `application/problem+json` (`#error-responses`)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Self

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


class _Coded(AAuthError):
    """An `AAuthError` whose code is fixed by its class."""

    code: str
    default_status: int

    def __init__(
        self,
        detail: str = "",
        *,
        status: int | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        super().__init__(
            status or self.default_status, self.code, detail, headers
        )


class InvalidRequest(_Coded):
    code, default_status = "invalid_request", 400


class InvalidCode(_Coded):
    """A pending URL that has already answered, or never existed (`#pending-url-security`)."""

    code, default_status = "invalid_code", 410


class Expired(_Coded):
    code, default_status = "expired", 408


class NotFound(_Coded):
    code, default_status = "not_found", 404


class MissionNotFound(_Coded):
    code, default_status = "mission_not_found", 404


class MissionTerminated(_Coded):
    code, default_status = "mission_terminated", 403


class AccessDenied(_Coded):
    code, default_status = "access_denied", 403


class Denied(_Coded):
    code, default_status = "denied", 403


class ServerError(_Coded):
    code, default_status = "server_error", 500


class Unauthorized(AAuthError):
    """`401`: the request's signature or agent does not verify."""

    def __init__(
        self, error: str, detail: str, headers: Mapping[str, str] | None = None
    ):
        super().__init__(401, error, detail, headers)

    @classmethod
    def rejected(
        cls, exc: VerificationError, headers: Mapping[str, str] | None = None
    ) -> Self:
        return cls(exc.code, exc.detail, headers)


class InvalidToken(AAuthError):
    """`400 invalid_<token>_token`, for a token the request carries."""

    def __init__(self, token: str, detail: str, *, expired: bool = False):
        prefix = "expired" if expired else "invalid"
        super().__init__(400, f"{prefix}_{token}_token", detail)

    @classmethod
    def rejected(cls, token: str, exc: VerificationError) -> Self:
        return cls(token, exc.detail, expired=exc.code == "expired_jwt")
