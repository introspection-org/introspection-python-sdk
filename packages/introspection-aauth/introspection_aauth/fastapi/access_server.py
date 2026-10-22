"""FastAPI routers for an Access Server's protocol routes and its well-known
documents."""

from fastapi import APIRouter

from introspection_aauth.access_server.server import AccessServer
from introspection_aauth.fastapi.routes import (
    PENDING_RESPONSE,
    SIGNED,
    Resolver,
    endpoint_base_path,
    finder,
    fixed,
    relative_path,
    signed_route,
    well_known_router,
)
from introspection_aauth.protocol.wire import (
    AccessServerMetadata,
    AuthTokenAnswer,
    TokenRequest,
)

#: Finds the AccessServer that serves a request, or None when there is none.
AccessServerResolver = Resolver[AccessServer]


def access_server_well_known_router(
    server: AccessServer | AccessServerResolver,
    router: APIRouter | None = None,
    *,
    cache_control: str | None = None,
) -> APIRouter:
    """The Access Server's metadata and keys, to mount at the root."""
    return well_known_router(
        APIRouter() if router is None else router,
        finder(fixed(server) if isinstance(server, AccessServer) else server),
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
    find = finder(
        fixed(server) if isinstance(server, AccessServer) else server
    )
    router = APIRouter() if router is None else router
    if not router.prefix:
        access_server_well_known_router(server, router)
    prefix = relative_path(router, endpoint_base_path(server, endpoint_path))
    signed_route(
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
    signed_route(
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
