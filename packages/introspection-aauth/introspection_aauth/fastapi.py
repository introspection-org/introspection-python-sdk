"""FastAPI routers for either server (`pip install introspection-aauth[fastapi]`).

Each router serves its server's well-known documents at the root and its
protocol routes under the path of its `endpoint_base`. A request is verified
as its signer addressed it, at `endpoint_base`, whatever proxy delivered it.
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


def person_server_router(ps: PersonServer) -> APIRouter:
    router = APIRouter()
    base = ps.endpoint_base
    prefix = urlsplit(base).path

    @router.get("/.well-known/aauth-person.json")
    async def metadata() -> JSONResponse:
        return JSONResponse(ps.metadata())

    @router.get("/.well-known/aauth-person-jwks.json")
    async def jwks() -> JSONResponse:
        return JSONResponse(ps.jwks())

    @router.post(f"{prefix}/mission")
    async def mission(request: Request) -> JSONResponse:
        return await _serve(request, base, ps.propose_mission)

    @router.post(prefix + "/mission/{s256}")
    async def mission_action(request: Request, s256: str) -> JSONResponse:
        return await _serve(
            request, base, lambda r: ps.mission_action(r, s256)
        )

    @router.post(f"{prefix}/person-token")
    async def person_token(request: Request) -> JSONResponse:
        return await _serve(request, base, ps.person_token)

    @router.post(f"{prefix}/token")
    async def auth_token(request: Request) -> JSONResponse:
        return await _serve(request, base, ps.auth_token)

    @router.get(prefix + "/pending/{tenant}/{approval_id}")
    async def poll(
        request: Request, tenant: str, approval_id: str
    ) -> JSONResponse:
        return await _serve(
            request, base, lambda r: ps.poll(r, tenant, approval_id)
        )

    return router


def access_server_router(server: AccessServer) -> APIRouter:
    router = APIRouter()
    base = server.endpoint_base
    prefix = urlsplit(base).path

    @router.get("/.well-known/aauth-access.json")
    async def metadata() -> JSONResponse:
        return JSONResponse(server.metadata())

    @router.get("/.well-known/aauth-access-jwks.json")
    async def jwks() -> JSONResponse:
        return JSONResponse(server.jwks())

    @router.post(f"{prefix}/token")
    async def token(request: Request) -> JSONResponse:
        return await _serve(request, base, server.token)

    @router.get(prefix + "/pending/{pending_id}")
    async def poll(request: Request, pending_id: str) -> JSONResponse:
        return await _serve(
            request, base, lambda r: server.poll(r, pending_id)
        )

    return router
