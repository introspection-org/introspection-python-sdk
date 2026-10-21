"""FastAPI routers for either server (`pip install introspection-aauth[fastapi]`).

Each server has two routers: its protocol routes, at the path of its
`endpoint_base`, and its well-known documents, at the root. Pass an
`APIRouter` of your own to either, to set its tags, dependencies, responses or
`include_in_schema`. A protocol router may carry a prefix, which must be the
start of the endpoint base's path: its routes are then the rest of it. A
router without a prefix gets the well-known documents too, as one router for
the whole server. A request is verified as its signer addressed it, at
`endpoint_base`, whatever proxy delivered it.
"""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .access_server.server import AccessServer
from .person_server.server import PersonServer
from .protocol.errors import AAuthError, Answer
from .protocol.httpsig import SignedRequest

Handler = Callable[[SignedRequest], Awaitable[Answer]]


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


def _under(router: APIRouter, base: str) -> str:
    """The endpoint base's path, less the router's prefix."""
    path = urlsplit(base).path
    if not path.startswith(router.prefix):
        raise ValueError(
            f"the router's prefix {router.prefix!r} is not the start of "
            f"the endpoint base's path {path!r}"
        )
    return path.removeprefix(router.prefix)


def person_server_well_known_router(
    ps: PersonServer, router: APIRouter | None = None
) -> APIRouter:
    """The Person Server's metadata and keys, to mount at the root."""
    router = APIRouter() if router is None else router

    @router.get(
        "/.well-known/aauth-person.json",
        summary="Person Server metadata",
        operation_id="aauth_person_server_metadata",
    )
    async def metadata() -> JSONResponse:
        return JSONResponse(ps.metadata())

    @router.get(
        "/.well-known/aauth-person-jwks.json",
        summary="Person Server signing keys",
        operation_id="aauth_person_server_jwks",
    )
    async def jwks() -> JSONResponse:
        return JSONResponse(ps.jwks())

    return router


def person_server_router(
    ps: PersonServer, router: APIRouter | None = None
) -> APIRouter:
    """The Person Server's protocol routes, and its well-known documents
    when `router` has no prefix."""
    router = APIRouter() if router is None else router
    base = ps.endpoint_base
    prefix = _under(router, base)
    if not router.prefix:
        person_server_well_known_router(ps, router)

    @router.post(
        f"{prefix}/mission",
        summary="Propose a mission",
        operation_id="aauth_person_server_propose_mission",
    )
    async def mission(request: Request) -> JSONResponse:
        return await _serve(request, base, ps.propose_mission)

    @router.post(
        prefix + "/mission/{s256}",
        summary="Act on a mission",
        operation_id="aauth_person_server_mission_action",
    )
    async def mission_action(request: Request, s256: str) -> JSONResponse:
        return await _serve(
            request, base, lambda r: ps.mission_action(r, s256)
        )

    @router.post(
        f"{prefix}/person-token",
        summary="Request a person token",
        operation_id="aauth_person_server_person_token",
    )
    async def person_token(request: Request) -> JSONResponse:
        return await _serve(request, base, ps.person_token)

    @router.post(
        f"{prefix}/token",
        summary="Request an auth token",
        operation_id="aauth_person_server_auth_token",
    )
    async def auth_token(request: Request) -> JSONResponse:
        return await _serve(request, base, ps.auth_token)

    @router.get(
        prefix + "/pending/{tenant}/{approval_id}",
        summary="Poll a pending request",
        operation_id="aauth_person_server_poll",
    )
    async def poll(
        request: Request, tenant: str, approval_id: str
    ) -> JSONResponse:
        return await _serve(
            request, base, lambda r: ps.poll(r, tenant, approval_id)
        )

    return router


def access_server_well_known_router(
    server: AccessServer, router: APIRouter | None = None
) -> APIRouter:
    """The Access Server's metadata and keys, to mount at the root."""
    router = APIRouter() if router is None else router

    @router.get(
        "/.well-known/aauth-access.json",
        summary="Access Server metadata",
        operation_id="aauth_access_server_metadata",
    )
    async def metadata() -> JSONResponse:
        return JSONResponse(server.metadata())

    @router.get(
        "/.well-known/aauth-access-jwks.json",
        summary="Access Server signing keys",
        operation_id="aauth_access_server_jwks",
    )
    async def jwks() -> JSONResponse:
        return JSONResponse(server.jwks())

    return router


def access_server_router(
    server: AccessServer, router: APIRouter | None = None
) -> APIRouter:
    """The Access Server's protocol routes, and its well-known documents
    when `router` has no prefix."""
    router = APIRouter() if router is None else router
    base = server.endpoint_base
    prefix = _under(router, base)
    if not router.prefix:
        access_server_well_known_router(server, router)

    @router.post(
        f"{prefix}/token",
        summary="Request an auth token, as a Person Server",
        operation_id="aauth_access_server_token",
    )
    async def token(request: Request) -> JSONResponse:
        return await _serve(request, base, server.token)

    @router.get(
        prefix + "/pending/{pending_id}",
        summary="Poll a pending request, as the Person Server that asked",
        operation_id="aauth_access_server_poll",
    )
    async def poll(request: Request, pending_id: str) -> JSONResponse:
        return await _serve(
            request, base, lambda r: server.poll(r, pending_id)
        )

    return router
