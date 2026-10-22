"""The plumbing every AAuth route shares: serving a signed request through a
server found per request, its documented answers, and the well-known
documents router."""

from collections.abc import Awaitable
from http import HTTPStatus
from types import UnionType
from typing import Protocol, TypedDict, TypeVar, Unpack
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, JsonValue

from introspection_aauth.protocol.answer import Answer
from introspection_aauth.protocol.errors import (
    AAuthError,
    Problem,
)
from introspection_aauth.protocol.httpsig import SignedRequest
from introspection_aauth.protocol.json import JsonObject
from introspection_aauth.protocol.keys import Jwks
from introspection_aauth.protocol.server import Server
from introspection_aauth.protocol.wire import (
    Pending,
)

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


def body_schema(model: type[BaseModel]) -> JsonObject:
    """The signed JSON body, read raw so the signature covers its bytes."""
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": model.model_json_schema()}
            },
        }
    }


def json_response(
    model: BaseModel, cache_control: str | None = None
) -> Response:
    response = Response(
        model.model_dump_json(exclude_none=True),
        media_type="application/json",
    )
    if cache_control:
        response.headers["Cache-Control"] = cache_control
    return response


def respond(answer: Answer) -> Response:
    headers = dict(answer.headers)
    media_type = headers.pop("Content-Type", "application/json")
    return Response(answer.content(), answer.status, headers, media_type)


def raw_target(request: Request) -> tuple[str, str]:
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


async def serve(request: Request, base: str, handle: Handler) -> Response:
    raw_path, raw_query = raw_target(request)
    path = raw_path.removeprefix(urlsplit(base).path)
    query = f"?{raw_query}" if raw_query else ""
    signed = SignedRequest(
        request.method,
        f"{base}{path}{query}",
        dict(request.headers),
        (await request.body()) or None,
    )
    try:
        return respond(await handle(signed))
    except AAuthError as exc:
        return respond(exc.answer())


def relative_path(router: APIRouter, path: str) -> str:
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


def fixed(server: AnyServer) -> Resolver[AnyServer]:
    return lambda request: server


def finder(resolve: Resolver[AnyServer]) -> Finder[AnyServer]:
    def find(request: Request) -> AnyServer:
        server = resolve(request)
        if server is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND)
        return server

    return find


def well_known_router(
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
        return json_response(find(request).metadata(), cache_control)

    @router.get(
        f"/.well-known/aauth-{role}-jwks.json",
        summary=f"{title} signing keys",
        operation_id=f"aauth_{role}_server_jwks",
        response_model=Jwks,
    )
    async def jwks(request: Request) -> Response:
        return json_response(find(request).jwks(), cache_control)

    return router


def endpoint_base_path(
    source: Server | Resolver[Server],
    endpoint_path: str | None,
) -> str:
    if isinstance(source, Server):
        return urlsplit(source.endpoint_base).path
    if endpoint_path is None:
        raise ValueError("a resolver needs the endpoint base's path")
    return endpoint_path.rstrip("/")


class Action(Protocol[ActingServer]):
    """A server's answer to one signed request, given its path parameters."""

    def __call__(
        self,
        server: ActingServer,
        signed: SignedRequest,
        path: dict[str, str],
        /,
    ) -> Awaitable[Answer]: ...


def path_parameters(path: str) -> list[JsonValue]:
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


def signed_route(
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
    extra: JsonObject = body_schema(body) if body is not None else {}
    if parameters := path_parameters(path):
        extra["parameters"] = parameters

    async def endpoint(request: Request) -> Response:
        server = find(request)

        async def handle(signed: SignedRequest) -> Answer:
            return await act(server, signed, dict(request.path_params))

        return await serve(request, server.endpoint_base, handle)

    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        openapi_extra=extra or None,
        responses={code: {**r} for code, r in (responses or {}).items()},
        **docs,
    )
