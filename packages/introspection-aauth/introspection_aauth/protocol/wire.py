"""What AAuth's servers send and receive over HTTP: every body is one of
these models, parsed at the boundary and serialised with members that are
None left out."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from introspection_aauth.protocol.errors import Problem
from introspection_aauth.protocol.keys import Jwks
from introspection_aauth.protocol.models import Budget


class Wire(BaseModel):
    """A body on the wire: members that are None are left out."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    def to_json(self) -> bytes:
        return self.model_dump_json(exclude_none=True).encode()


class Pending(Wire):
    """The body of a `202`: poll its `Location` (`#deferred-responses`)."""

    status: Literal["pending"] = "pending"


class Empty(Wire):
    """A `200` with nothing more to say."""


class ServerMetadata(Wire):
    """Any AAuth server's metadata, as far as finding its keys goes
    (`#metadata-documents`)."""

    issuer: str
    jwks_uri: str | None = None
    jwks: Jwks | None = None


class PersonServerMetadata(Wire):
    """`/.well-known/aauth-person.json` (`#ps-metadata`)."""

    issuer: str
    name: str | None = None
    jwks_uri: str
    person_token_endpoint: str
    auth_token_endpoint: str
    mission_endpoint: str
    claims_supported: list[str]


class AccessServerMetadata(Wire):
    """`/.well-known/aauth-access.json` (`#as-metadata`)."""

    issuer: str
    name: str | None = None
    jwks_uri: str
    auth_token_endpoint: str


class TokenRequest(Wire):
    """A Person Server's request to an Access Server (`#ps-to-as-token-request`),
    with the budget it allows (draft-hardt-aauth-budgets)."""

    resource_token: str
    agent_token: str
    presented_token: str
    budget: Budget | None = None
    upstream_token: str | None = None
    subagent_token: str | None = None


class AuthTokenAnswer(Wire):
    auth_token: str
    expires_in: int


class PersonTokenAnswer(Wire):
    person_token: str
    expires_in: int


class R3Display(Wire):
    summary: str | None = None


class R3Proposal(Wire):
    """A resource's R3 proposal, as far as a server shows it to a person."""

    display: R3Display | None = None


__all__ = [
    "AccessServerMetadata",
    "AuthTokenAnswer",
    "Empty",
    "Pending",
    "PersonServerMetadata",
    "PersonTokenAnswer",
    "Problem",
    "R3Display",
    "R3Proposal",
    "ServerMetadata",
    "TokenRequest",
    "Wire",
]
