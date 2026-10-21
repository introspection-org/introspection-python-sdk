import pytest
from fastapi import APIRouter, FastAPI

from introspection_aauth.fastapi import (
    access_server_router,
    person_server_router,
    person_server_well_known_router,
)

from .world import World


def paths(app: FastAPI) -> dict[str, dict]:
    return app.openapi()["paths"]


def test_one_router_serves_the_whole_person_server():
    app = FastAPI()
    app.include_router(person_server_router(World().ps))
    served = paths(app)
    assert "/.well-known/aauth-person.json" in served
    assert "/aauth/token" in served
    assert (
        served["/aauth/token"]["post"]["operationId"]
        == "aauth_person_server_auth_token"
    )


def test_a_host_router_carries_its_tags_and_prefix():
    ps = World().ps
    app = FastAPI()
    app.include_router(
        person_server_router(ps, APIRouter(prefix="/aauth", tags=["AAuth"]))
    )
    app.include_router(person_server_well_known_router(ps))
    served = paths(app)
    assert served["/aauth/token"]["post"]["tags"] == ["AAuth"]
    assert served["/aauth/pending/{tenant}/{approval_id}"]["get"]["tags"] == [
        "AAuth"
    ]
    assert "tags" not in served["/.well-known/aauth-person.json"]["get"]
    assert "/aauth/.well-known/aauth-person.json" not in served


def test_a_prefix_outside_the_endpoint_base_is_refused():
    with pytest.raises(ValueError, match="endpoint base"):
        person_server_router(World().ps, APIRouter(prefix="/elsewhere"))


def test_a_router_can_leave_the_access_server_out_of_the_schema():
    app = FastAPI()
    app.include_router(
        access_server_router(
            World().access, APIRouter(include_in_schema=False)
        )
    )
    assert paths(app) == {}
