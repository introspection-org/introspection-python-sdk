"""FastAPI routers for either server (`pip install introspection-aauth[fastapi]`).

Each server has two routers: its protocol routes, at the path of its
`endpoint_base`, and its well-known documents, at the root. Pass an
`APIRouter` of your own to either, to set its tags, dependencies, responses or
`include_in_schema`. A protocol router may carry a prefix, which must be the
start of the endpoint base's path: its routes are then the rest of it. A
router without a prefix gets the well-known documents too, as one router for
the whole server.

A host that builds its server after the app (at startup, or only when a
feature is on) passes a resolver instead of the server, with the endpoint
base's path: the resolver finds the server for each request, and a request it
finds none for is answered `404`.

A request is verified as its signer addressed it, at `endpoint_base`,
whatever proxy delivered it.
"""

from collections.abc import Awaitable
from http import HTTPStatus
from types import UnionType
from typing import Protocol, TypedDict, TypeVar, Unpack
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, JsonValue

from introspection_aauth.access_server.server import AccessServer
from introspection_aauth.person_server.models import (
    AuthTokenRequest,
    MissionAction,
    MissionAnswer,
    MissionLogged,
    MissionProposal,
    PersonTokenRequest,
)
from introspection_aauth.person_server.server import PersonServer
from introspection_aauth.protocol.answer import Answer
from introspection_aauth.protocol.errors import (
    AAuthError,
    NotFound,
    Problem,
)
from introspection_aauth.protocol.httpsig import SignedRequest
from introspection_aauth.protocol.json import JsonObject
from introspection_aauth.protocol.keys import Jwks
from introspection_aauth.protocol.server import Server
from introspection_aauth.protocol.wire import (
    AccessServerMetadata,
    AuthTokenAnswer,
    Empty,
    Pending,
    PersonServerMetadata,
    PersonTokenAnswer,
    TokenRequest,
)

__all__ = [
    "AccessServerResolver",
    "PersonServerResolver",
    "access_server_router",
    "access_server_well_known_router",
    "person_server_router",
    "person_server_well_known_router",
]

FoundServer = TypeVar("FoundServer", bound=Server, covariant=True)
AnyServer = TypeVar("AnyServer", bound=Server)
ActingServer = TypeVar("ActingServer", bound=Server, contravariant=True)


class DocumentedResponse(TypedDict, total=False):
    """One of a route's documented responses."""

    model: type[BaseModel]
    description: str
    content: JsonObject


Responses = dict[int | str, DocumentedResponse]


class RouteDocs(TypedDict, total=False):
    summary: str
    description: str
    operation_id: str
    status_code: int
    response_model: type[BaseModel] | UnionType


class PersonServerResolver(Protocol):
    """The Person Server that serves `request`, or None when there is none."""

    def __call__(self, request: Request) -> PersonServer | None: ...


class AccessServerResolver(Protocol):
    """The Access Server that serves `request`, or None when there is none."""

    def __call__(self, request: Request) -> AccessServer | None: ...


class Handler(Protocol):
    """A server's answer to one signed request."""

    def __call__(self, request: SignedRequest, /) -> Awaitable[Answer]: ...


SIGNED = (
    "Signed: the request carries an RFC 9421 signature with `Signature-Key`, "
    "and errors are AAuth problem+json."
)
PROBLEM_RESPONSES: Responses = {
    "4XX": {
        "model": Problem,
        "description": "Refused",
        "content": {"application/problem+json": {}},
    },
}
PENDING_RESPONSE: Responses = {
    HTTPStatus.ACCEPTED.value: {
        "model": Pending,
        "description": "Put to whoever decides; poll the `Location` it names",
    },
    **PROBLEM_RESPONSES,
}


def _body(model: type[BaseModel]) -> JsonObject:
    """The signed JSON body, read raw so the signature covers its bytes."""
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": model.model_json_schema()}
            },
        }
    }


def _json(model: BaseModel, cache_control: str | None = None) -> Response:
    response = Response(
        model.model_dump_json(exclude_none=True),
        media_type="application/json",
    )
    if cache_control:
        response.headers["Cache-Control"] = cache_control
    return response


def _respond(answer: Answer) -> Response:
    headers = dict(answer.headers)
    media_type = headers.pop("Content-Type", "application/json")
    return Response(answer.content(), answer.status, headers, media_type)


def _raw_target(request: Request) -> tuple[str, str]:
    """The path and query as the signer sent them, still percent-encoded:
    what `@path` and `@query` cover, which the decoded path is not."""
    raw_path = request.scope.get("raw_path")
    path = (
        raw_path.decode("latin-1")
        if isinstance(raw_path, bytes)
        else request.url.path
    )
    query = request.scope.get("query_string", b"")
    return path, query.decode("latin-1") if isinstance(query, bytes) else ""


async def _serve(request: Request, base: str, handle: Handler) -> Response:
    raw_path, raw_query = _raw_target(request)
    path = raw_path.removeprefix(urlsplit(base).path)
    query = f"?{raw_query}" if raw_query else ""
    signed = SignedRequest(
        request.method,
        f"{base}{path}{query}",
        dict(request.headers),
        (await request.body()) or None,
    )
    try:
        return _respond(await handle(signed))
    except AAuthError as exc:
        return _respond(exc.answer())


def _under(router: APIRouter, path: str) -> str:
    """The endpoint base's path, less the router's prefix."""
    if not path.startswith(router.prefix):
        raise ValueError(
            f"the router's prefix {router.prefix!r} is not the start of "
            f"the endpoint base's path {path!r}"
        )
    return path.removeprefix(router.prefix)


class Resolver(Protocol[FoundServer]):
    def __call__(self, request: Request) -> FoundServer | None: ...


class Finder(Protocol[FoundServer]):
    def __call__(self, request: Request) -> FoundServer: ...


def _fixed(server: AnyServer) -> Resolver[AnyServer]:
    return lambda request: server


def _finder(resolve: Resolver[AnyServer]) -> Finder[AnyServer]:
    def find(request: Request) -> AnyServer:
        server = resolve(request)
        if server is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return server

    return find


def _well_known(
    router: APIRouter,
    find: Finder[Server],
    *,
    role: str,
    title: str,
    metadata_model: type[BaseModel],
    cache_control: str | None,
) -> APIRouter:
    """`/.well-known/aauth-{role}.json` and its keys."""

    @router.get(
        f"/.well-known/aauth-{role}.json",
        summary=f"{title} metadata",
        description="Its AAuth discovery document: issuer, keys, endpoints.",
        operation_id=f"aauth_{role}_server_metadata",
        response_model=metadata_model,
    )
    async def metadata(request: Request) -> Response:
        return _json(find(request).metadata(), cache_control)

    @router.get(
        f"/.well-known/aauth-{role}-jwks.json",
        summary=f"{title} signing keys",
        operation_id=f"aauth_{role}_server_jwks",
        response_model=Jwks,
    )
    async def jwks(request: Request) -> Response:
        return _json(find(request).jwks(), cache_control)

    return router


def _endpoint_path(
    source: PersonServer
    | AccessServer
    | PersonServerResolver
    | AccessServerResolver,
    endpoint_path: str | None,
) -> str:
    if isinstance(source, (PersonServer, AccessServer)):
        return urlsplit(source.endpoint_base).path
    if endpoint_path is None:
        raise ValueError("a resolver needs the endpoint base's path")
    return endpoint_path.rstrip("/")


def person_server_well_known_router(
    ps: PersonServer | PersonServerResolver,
    router: APIRouter | None = None,
    *,
    cache_control: str | None = None,
) -> APIRouter:
    """The Person Server's metadata and keys, to mount at the root."""
    return _well_known(
        APIRouter() if router is None else router,
        _finder(_fixed(ps) if isinstance(ps, PersonServer) else ps),
        role="person",
        title="Person Server",
        metadata_model=PersonServerMetadata,
        cache_control=cache_control,
    )


class Action(Protocol[ActingServer]):
    """A server's answer to one signed request, given its path parameters."""

    def __call__(
        self,
        server: ActingServer,
        signed: SignedRequest,
        path: dict[str, str],
        /,
    ) -> Awaitable[Answer]: ...


def _parameters(path: str) -> list[JsonValue]:
    names = [
        segment.strip("{}").split(":")[0]
        for segment in path.split("/")
        if segment.startswith("{")
    ]
    return [
        {
            "name": n,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
        for n in names
    ]


def _signed_route(
    router: APIRouter,
    method: str,
    path: str,
    find: Finder[AnyServer],
    act: Action[AnyServer],
    *,
    body: type[BaseModel] | None = None,
    responses: Responses | None = None,
    **docs: Unpack[RouteDocs],
) -> None:
    """A signed protocol route: the server `find` resolves answers it by `act`."""
    extra: JsonObject = _body(body) if body is not None else {}
    if parameters := _parameters(path):
        extra["parameters"] = parameters

    async def endpoint(request: Request) -> Response:
        server = find(request)

        async def handle(signed: SignedRequest) -> Answer:
            return await act(server, signed, dict(request.path_params))

        return await _serve(request, server.endpoint_base, handle)

    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        openapi_extra=extra or None,
        responses={code: {**r} for code, r in (responses or {}).items()},
        **docs,
    )


async def _poll_person_server(
    server: PersonServer, signed: SignedRequest, path: dict[str, str]
) -> Answer:
    # Read from the signed URL, still encoded, so it is decoded once.
    under = f"{urlsplit(server.endpoint_base).path}/pending/"
    parts = server.pending_parts(urlsplit(signed.url).path.removeprefix(under))
    if parts is None:
        raise NotFound("no such pending request")
    return await server.poll(signed, *parts)


def person_server_router(
    ps: PersonServer | PersonServerResolver,
    router: APIRouter | None = None,
    *,
    endpoint_path: str | None = None,
) -> APIRouter:
    """The Person Server's protocol routes, and its well-known documents
    when `router` has no prefix. With a resolver, `endpoint_path` is the
    path of its servers' endpoint base."""
    router = APIRouter() if router is None else router
    prefix = _under(router, _endpoint_path(ps, endpoint_path))
    find = _finder(_fixed(ps) if isinstance(ps, PersonServer) else ps)
    if not router.prefix:
        person_server_well_known_router(ps, router)
    _signed_route(
        router,
        "POST",
        f"{prefix}/mission",
        find,
        lambda server, signed, _: server.propose_mission(signed),
        body=MissionProposal,
        summary="Propose a mission",
        description=f"Always put to an approver, who may set its budget. {SIGNED}",
        operation_id="aauth_person_server_propose_mission",
        status_code=HTTPStatus.ACCEPTED,
        response_model=Pending,
        responses=PROBLEM_RESPONSES,
    )
    _signed_route(
        router,
        "POST",
        prefix + "/mission/{s256}",
        find,
        lambda server, signed, path: server.mission_action(
            signed, path["s256"]
        ),
        body=MissionAction,
        summary="Log an update, or propose the mission complete",
        description=(
            "`action` is `update` or `completion`; a completion is put to "
            f"the mission's person. {SIGNED}"
        ),
        operation_id="aauth_person_server_mission_action",
        response_model=MissionLogged,
        responses=PENDING_RESPONSE,
    )
    _signed_route(
        router,
        "POST",
        f"{prefix}/person-token",
        find,
        lambda server, signed, _: server.person_token(signed),
        body=PersonTokenRequest,
        summary="Get a person token",
        description=(
            "Who the agent acts for, at one resource, under a mission it "
            f"holds. {SIGNED}"
        ),
        operation_id="aauth_person_server_person_token",
        response_model=PersonTokenAnswer,
        responses=PROBLEM_RESPONSES,
    )
    _signed_route(
        router,
        "POST",
        f"{prefix}/token",
        find,
        lambda server, signed, _: server.auth_token(signed),
        body=AuthTokenRequest,
        summary="Exchange a resource token for an auth token",
        description=(
            "Issued at once within the mission's budget and spent; over what "
            f"is left, put to an approver. {SIGNED}"
        ),
        operation_id="aauth_person_server_auth_token",
        response_model=AuthTokenAnswer,
        responses=PENDING_RESPONSE,
    )
    _signed_route(
        router,
        "GET",
        prefix + "/pending/{pending_path:path}",
        find,
        _poll_person_server,
        summary="Poll a pending request",
        description=(
            "Only the key that asked may read it: `202` while pending, `200` "
            "with the result once decided, `403` when declined, `408` once it "
            f"expires, `410` once collected. {SIGNED}"
        ),
        operation_id="aauth_person_server_poll",
        response_model=AuthTokenAnswer | MissionAnswer | Empty,
        responses=PENDING_RESPONSE,
    )
    return router


def access_server_well_known_router(
    server: AccessServer | AccessServerResolver,
    router: APIRouter | None = None,
    *,
    cache_control: str | None = None,
) -> APIRouter:
    """The Access Server's metadata and keys, to mount at the root."""
    return _well_known(
        APIRouter() if router is None else router,
        _finder(
            _fixed(server) if isinstance(server, AccessServer) else server
        ),
        role="access",
        title="Access Server",
        metadata_model=AccessServerMetadata,
        cache_control=cache_control,
    )


def access_server_router(
    server: AccessServer | AccessServerResolver,
    router: APIRouter | None = None,
    *,
    endpoint_path: str | None = None,
) -> APIRouter:
    """As `person_server_router`, for an Access Server."""
    find = _finder(
        _fixed(server) if isinstance(server, AccessServer) else server
    )
    router = APIRouter() if router is None else router
    if not router.prefix:
        access_server_well_known_router(server, router)
    prefix = _under(router, _endpoint_path(server, endpoint_path))
    _signed_route(
        router,
        "POST",
        f"{prefix}/token",
        find,
        lambda found, signed, _: found.token(signed),
        body=TokenRequest,
        summary="Request an auth token, as a Person Server",
        description=(
            "A Person Server's signed request with the resource, agent and "
            "presented tokens; issued, refused, or `202` while the resource's "
            f"policy waits on someone. {SIGNED}"
        ),
        operation_id="aauth_access_server_token",
        response_model=AuthTokenAnswer,
        responses=PENDING_RESPONSE,
    )
    _signed_route(
        router,
        "GET",
        prefix + "/pending/{pending_id}",
        find,
        lambda found, signed, path: found.poll(signed, path["pending_id"]),
        summary="Poll a pending request, as the Person Server that asked",
        operation_id="aauth_access_server_poll",
        response_model=AuthTokenAnswer,
        responses=PENDING_RESPONSE,
    )
    return router
