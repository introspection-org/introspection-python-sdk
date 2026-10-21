"""What a Person Server and an Access Server both do as servers: sign as
themselves, verify the agents and servers that call them, read a resource's
R3 proposal, and answer a request that has to wait."""

import logging
import time
import uuid
from collections.abc import Sequence
from typing import NotRequired, Protocol, TypedDict, TypeVar, Unpack

import httpx2 as httpx
from pydantic import BaseModel, ValidationError

from introspection_aauth.protocol.claims import (
    ACCESS_DWK,
    AGENT_DWK,
    PERSON_DWK,
    RESOURCE_DWK,
    ServerDwk,
)
from introspection_aauth.protocol.discovery import Discovery
from introspection_aauth.protocol.errors import (
    InvalidRequest,
)
from introspection_aauth.protocol.identity import Identity
from introspection_aauth.protocol.keys import Jwks, SigningKey

__all__ = [
    "ACCESS_DWK",
    "AGENT_DWK",
    "PERSON_DWK",
    "RESOURCE_DWK",
    "Clock",
    "IdFactory",
    "Server",
    "ServerOptions",
    "now_seconds",
    "parse",
]

logger = logging.getLogger(__name__)

Model = TypeVar("Model", bound=BaseModel)


def now_seconds() -> int:
    return int(time.time())


def parse(model: type[Model], body: bytes | None) -> Model:
    """A request body, or `400 invalid_request`."""
    try:
        return model.model_validate_json(body or b"{}")
    except ValidationError as exc:
        raise InvalidRequest(exc.errors()[0]["msg"]) from None


def new_hex_id() -> str:
    return uuid.uuid4().hex


class Clock(Protocol):
    """Now, in whole seconds since the epoch."""

    def __call__(self) -> int: ...


class IdFactory(Protocol):
    """A new id, unique to this server."""

    def __call__(self) -> str: ...


class ServerOptions(TypedDict):
    """What every server takes besides its own: its keys' predecessors, where
    its protocol routes live, its clock and ids, and how long to wait."""

    previous_keys: NotRequired[Sequence[SigningKey]]
    #: The URL its protocol routes are under, e.g. `{issuer}/aauth`.
    endpoint_base: NotRequired[str]
    retry_after: NotRequired[int]
    clock: NotRequired[Clock]
    new_id: NotRequired[IdFactory]
    name: NotRequired[str]
    #: How it reads metadata and keys; by default, over its `http`.
    discovery: NotRequired[Discovery]


class Server:
    """A server's identity, its HTTP client and discovery, and its options."""

    def __init__(
        self,
        issuer: str,
        dwk: ServerDwk,
        signing_key: SigningKey,
        http: httpx.AsyncClient,
        **options: Unpack[ServerOptions],
    ):
        self.identity = Identity(
            issuer, dwk, signing_key, options.get("previous_keys", ())
        )
        self.issuer = self.identity.issuer
        self.http = http
        self.discovery = options.get("discovery") or Discovery(http)
        self.endpoint_base = options.get("endpoint_base", self.issuer).rstrip(
            "/"
        )
        self.retry_after = options.get("retry_after", 5)
        self.clock: Clock = options.get("clock", now_seconds)
        self.new_id: IdFactory = options.get("new_id", new_hex_id)
        self.name = options.get("name")

    def jwks(self) -> Jwks:
        return self.identity.jwks()

    def metadata(self) -> BaseModel:
        """Its `/.well-known` metadata document."""
        raise NotImplementedError
