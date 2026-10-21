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
from typing import Protocol, TypedDict, TypeVar, Unpack
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from .access_server.server import AccessServer
from .person_server.models import (
    AuthTokenRequest,
    MissionAction,
    MissionAnswer,
    MissionLogged,
    MissionProposal,
    PersonTokenRequest,
)
from .person_server.server import PersonServer
from .protocol.errors import AAuthError, Answer, Problem
from .protocol.httpsig import SignedRequest
from .protocol.keys import Jwks
from .protocol.server import Server
from .protocol.wire import (
    AccessServerMetadata,
    AuthTokenAnswer,
    Empty,
    Pending,
    PersonServerMetadata,
    PersonTokenAnswer,
    TokenRequest,
)

_Found = TypeVar("_Found", bound=Server, covariant=True)
_Server = TypeVar("_Server", bound=Server)
_Acting = TypeVar("_Acting", bound=Server, contravariant=True)


class _Docs(TypedDict, total=False):
    summary: str
    description: str
    operation_id: str
    status_code: int
    response_model: object
    responses: dict[int | str, dict[str, object]]


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
PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    "4XX": {
        "model": Problem,
        "description": "Refused",
        "content": {"application/problem+json": {}},
    },
}
PENDING_RESPONSE: dict[int | str, dict[str, object]] = {
    HTTPStatus.ACCEPTED.value: {
        "model": Pending,
        "description": "Put to whoever decides; poll the `Location` it names",
    },
    **PROBLEM_RESPONSES,
}


def _body(model: type[BaseModel]) -> dict[str, object]:
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


async def _serve(request: Request, base: str, handle: Handler) -> Response:
    path = request.url.path.removeprefix(urlsplit(base).path)
    query = f"?{request.url.query}" if request.url.query else ""
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


class _Resolver(Protocol[_Found]):
    def __call__(self, request: Request) -> _Found | None: ...


class _Find(Protocol[_Found]):
    def __call__(self, request: Request) -> _Found: ...


def _fixed(server: _Server) -> _Resolver[_Server]:
    return lambda request: server


def _finder(resolve: _Resolver[_Server]) -> _Find[_Server]:
    def find(request: Request) -> _Server:
        server = resolve(request)
        if server is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return server

    return find


def _well_known(
    router: APIRouter,
    find: _Find[Server],
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
    source: PersonServer | AccessServer | object, endpoint_path: str | None
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


class _Act(Protocol[_Acting]):
    """A server's answer to one signed request, given its path parameters."""

    def __call__(
        self, server: _Acting, signed: SignedRequest, path: dict[str, str], /
    ) -> Awaitable[Answer]: ...


def _parameters(path: str) -> list[dict[str, object]]:
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
    find: _Find[_Server],
    act: _Act[_Server],
    *,
    body: type[BaseModel] | None = None,
    **docs: Unpack[_Docs],
) -> None:
    """A signed protocol route: the server `find` resolves answers it by `act`."""
    extra: dict[str, object] = _body(body) if body is not None else {}
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
        **docs,
    )


async def _poll_person_server(
    server: PersonServer, signed: SignedRequest, path: dict[str, str]
) -> Answer:
    parts = server.pending_parts(path["pending_path"])
    if parts is None:
        raise AAuthError(404, "not_found", "no such pending request")
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
