"""FastAPI routers for a Person Server's protocol routes and its well-known
documents."""

from http import HTTPStatus
from urllib.parse import urlsplit

from fastapi import APIRouter

from introspection_aauth.fastapi.routes import (
    PENDING_RESPONSE,
    PROBLEM_RESPONSES,
    SIGNED,
    Resolver,
    endpoint_base_path,
    finder,
    fixed,
    relative_path,
    signed_route,
    well_known_router,
)
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
    NotFound,
)
from introspection_aauth.protocol.httpsig import SignedRequest
from introspection_aauth.protocol.wire import (
    AuthTokenAnswer,
    Empty,
    Pending,
    PersonServerMetadata,
    PersonTokenAnswer,
)

#: Finds the PersonServer that serves a request, or None when there is none.
PersonServerResolver = Resolver[PersonServer]


def person_server_well_known_router(
    ps: PersonServer | PersonServerResolver,
    router: APIRouter | None = None,
    *,
    cache_control: str | None = None,
) -> APIRouter:
    """The Person Server's metadata and keys, to mount at the root."""
    return well_known_router(
        APIRouter() if router is None else router,
        finder(fixed(ps) if isinstance(ps, PersonServer) else ps),
        role="person",
        title="Person Server",
        metadata_model=PersonServerMetadata,
        cache_control=cache_control,
    )


async def poll_person_server(
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
    prefix = relative_path(router, endpoint_base_path(ps, endpoint_path))
    find = finder(fixed(ps) if isinstance(ps, PersonServer) else ps)
    if not router.prefix:
        person_server_well_known_router(ps, router)
    signed_route(
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
    signed_route(
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
    signed_route(
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
    signed_route(
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
    signed_route(
        router,
        "GET",
        prefix + "/pending/{pending_path:path}",
        find,
        poll_person_server,
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
