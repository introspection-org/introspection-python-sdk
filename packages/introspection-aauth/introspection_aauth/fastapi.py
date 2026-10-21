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
from typing import Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .access_server.models import TokenRequest
from .access_server.server import AccessServer
from .person_server.models import (
    AuthTokenRequest,
    MissionAction,
    MissionProposal,
    PersonTokenRequest,
)
from .person_server.server import PersonServer
from .protocol.errors import AAuthError, Answer
from .protocol.httpsig import SignedRequest


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
PENDING_RESPONSE: dict[int | str, dict[str, object]] = {
    HTTPStatus.ACCEPTED.value: {
        "description": "Put to whoever decides; poll the `Location` it names"
    }
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


def _respond(answer: Answer) -> JSONResponse:
    return JSONResponse(answer.body, answer.status, answer.headers)


async def _serve(request: Request, base: str, handle: Handler) -> JSONResponse:
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


def _cached(response: JSONResponse, cache_control: str | None) -> JSONResponse:
    if cache_control:
        response.headers["Cache-Control"] = cache_control
    return response


def _person(source: "PersonServer | PersonServerResolver"):
    def find(request: Request) -> PersonServer:
        server = (
            source if isinstance(source, PersonServer) else source(request)
        )
        if server is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return server

    return find


def _access(source: "AccessServer | AccessServerResolver"):
    def find(request: Request) -> AccessServer:
        server = (
            source if isinstance(source, AccessServer) else source(request)
        )
        if server is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return server

    return find


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
    router = APIRouter() if router is None else router
    find = _person(ps)

    @router.get(
        "/.well-known/aauth-person.json",
        summary="Person Server metadata",
        description="Its AAuth discovery document: issuer, keys, endpoints.",
        operation_id="aauth_person_server_metadata",
    )
    async def metadata(request: Request) -> JSONResponse:
        return _cached(JSONResponse(find(request).metadata()), cache_control)

    @router.get(
        "/.well-known/aauth-person-jwks.json",
        summary="Person Server signing keys",
        operation_id="aauth_person_server_jwks",
    )
    async def jwks(request: Request) -> JSONResponse:
        return _cached(JSONResponse(find(request).jwks()), cache_control)

    return router


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
    find = _person(ps)
    if not router.prefix:
        person_server_well_known_router(ps, router)

    @router.post(
        f"{prefix}/mission",
        summary="Propose a mission",
        description=f"Always put to an approver, who may set its budget. {SIGNED}",
        operation_id="aauth_person_server_propose_mission",
        openapi_extra=_body(MissionProposal),
        responses=PENDING_RESPONSE,
    )
    async def mission(request: Request) -> JSONResponse:
        server = find(request)
        return await _serve(
            request, server.endpoint_base, server.propose_mission
        )

    @router.post(
        prefix + "/mission/{s256}",
        summary="Log an update, or propose the mission complete",
        description=(
            "`action` is `update` or `completion`; a completion is put to "
            f"the mission's person. {SIGNED}"
        ),
        operation_id="aauth_person_server_mission_action",
        openapi_extra=_body(MissionAction),
        responses=PENDING_RESPONSE,
    )
    async def mission_action(request: Request, s256: str) -> JSONResponse:
        server = find(request)

        async def act(signed: SignedRequest) -> Answer:
            return await server.mission_action(signed, s256)

        return await _serve(request, server.endpoint_base, act)

    @router.post(
        f"{prefix}/person-token",
        summary="Get a person token",
        description=(
            "Who the agent acts for, at one resource, under a mission it "
            f"holds. {SIGNED}"
        ),
        operation_id="aauth_person_server_person_token",
        openapi_extra=_body(PersonTokenRequest),
    )
    async def person_token(request: Request) -> JSONResponse:
        server = find(request)
        return await _serve(request, server.endpoint_base, server.person_token)

    @router.post(
        f"{prefix}/token",
        summary="Exchange a resource token for an auth token",
        description=(
            "Issued at once within the mission's budget and spent; over what "
            f"is left, put to an approver. {SIGNED}"
        ),
        operation_id="aauth_person_server_auth_token",
        openapi_extra=_body(AuthTokenRequest),
        responses=PENDING_RESPONSE,
    )
    async def auth_token(request: Request) -> JSONResponse:
        server = find(request)
        return await _serve(request, server.endpoint_base, server.auth_token)

    @router.get(
        prefix + "/pending/{pending_path:path}",
        summary="Poll a pending request",
        description=(
            "Only the key that asked may read it: `202` while pending, `200` "
            "with the result once decided, `403` when declined, `408` once it "
            f"expires, `410` once collected. {SIGNED}"
        ),
        operation_id="aauth_person_server_poll",
        responses=PENDING_RESPONSE,
    )
    async def poll(request: Request, pending_path: str) -> JSONResponse:
        server = find(request)

        async def read(signed: SignedRequest) -> Answer:
            parts = server.pending_parts(pending_path)
            if parts is None:
                raise AAuthError(404, "not_found", "no such pending request")
            return await server.poll(signed, *parts)

        return await _serve(request, server.endpoint_base, read)

    return router


def access_server_well_known_router(
    server: AccessServer | AccessServerResolver,
    router: APIRouter | None = None,
    *,
    cache_control: str | None = None,
) -> APIRouter:
    """The Access Server's metadata and keys, to mount at the root."""
    router = APIRouter() if router is None else router
    find = _access(server)

    @router.get(
        "/.well-known/aauth-access.json",
        summary="Access Server metadata",
        description="Its AAuth discovery document: issuer, keys, token endpoint.",
        operation_id="aauth_access_server_metadata",
    )
    async def metadata(request: Request) -> JSONResponse:
        return _cached(JSONResponse(find(request).metadata()), cache_control)

    @router.get(
        "/.well-known/aauth-access-jwks.json",
        summary="Access Server signing keys",
        operation_id="aauth_access_server_jwks",
    )
    async def jwks(request: Request) -> JSONResponse:
        return _cached(JSONResponse(find(request).jwks()), cache_control)

    return router


def access_server_router(
    server: AccessServer | AccessServerResolver,
    router: APIRouter | None = None,
    *,
    endpoint_path: str | None = None,
) -> APIRouter:
    """The Access Server's protocol routes, and its well-known documents
    when `router` has no prefix. With a resolver, `endpoint_path` is the
    path of its servers' endpoint base."""
    router = APIRouter() if router is None else router
    prefix = _under(router, _endpoint_path(server, endpoint_path))
    find = _access(server)
    if not router.prefix:
        access_server_well_known_router(server, router)

    @router.post(
        f"{prefix}/token",
        summary="Request an auth token, as a Person Server",
        description=(
            "A Person Server's signed request with the resource, agent and "
            "presented tokens; issued, refused, or `202` while the resource's "
            f"policy waits on someone. {SIGNED}"
        ),
        operation_id="aauth_access_server_token",
        openapi_extra=_body(TokenRequest),
        responses=PENDING_RESPONSE,
    )
    async def token(request: Request) -> JSONResponse:
        found = find(request)
        return await _serve(request, found.endpoint_base, found.token)

    @router.get(
        prefix + "/pending/{pending_id}",
        summary="Poll a pending request, as the Person Server that asked",
        operation_id="aauth_access_server_poll",
        responses=PENDING_RESPONSE,
    )
    async def poll(request: Request, pending_id: str) -> JSONResponse:
        found = find(request)

        async def read(signed: SignedRequest) -> Answer:
            return await found.poll(signed, pending_id)

        return await _serve(request, found.endpoint_base, read)

    return router
