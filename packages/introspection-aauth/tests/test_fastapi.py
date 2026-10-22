import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from introspection_aauth.fastapi import (
    access_server_router,
    person_server_router,
    person_server_well_known_router,
)
from introspection_aauth.person_server import PersonServer
from introspection_aauth.protocol.json import JsonObject

from .world import World


def paths(app: FastAPI) -> dict[str, dict[str, JsonObject]]:
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
    assert served["/aauth/pending/{pending_path}"]["get"]["tags"] == ["AAuth"]
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


def test_a_pending_path_is_read_back_by_the_server_that_wrote_it():
    ps = World().ps
    assert ps.pending_parts("acme/a-1") == ("acme", "a-1")
    assert ps.pending_parts("a%3Ab/a-1") == ("a:b", "a-1")
    assert ps.pending_parts("a-1") is None
    assert ps.pending_parts("x/y/a-1") is None


def test_a_server_that_writes_another_pending_path_reads_it_back():
    class Scoped(PersonServer):
        def pending_url(self, tenant: str, approval_id: str) -> str:
            org, project = tenant.split(":")
            return (
                f"{self.endpoint_base}/pending/{org}/{project}/{approval_id}"
            )

        def pending_parts(self, path: str) -> tuple[str, str] | None:
            parts = path.split("/")
            return (
                (f"{parts[0]}:{parts[1]}", parts[2])
                if len(parts) == 3
                else None
            )

    world = World()
    ps = world.ps
    ps.__class__ = Scoped
    url = ps.pending_url("org:project", "a-1")
    assert url.endswith("/aauth/pending/org/project/a-1")
    assert ps.pending_parts(url.split("/pending/", 1)[1]) == (
        "org:project",
        "a-1",
    )


def test_the_well_known_documents_carry_the_cache_control_asked_for():
    app = FastAPI()
    app.include_router(
        person_server_well_known_router(
            World().ps, cache_control="public, max-age=300"
        )
    )
    with TestClient(app) as client:
        response = client.get("/.well-known/aauth-person.json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"


def test_a_resolver_that_finds_no_server_answers_404():
    server: list[PersonServer] = []
    app = FastAPI()
    app.include_router(
        person_server_router(
            lambda request: server[0] if server else None,
            APIRouter(prefix="/aauth"),
            endpoint_path="/aauth",
        )
    )
    app.include_router(
        person_server_well_known_router(
            lambda request: server[0] if server else None
        )
    )
    with TestClient(app) as client:
        assert client.get("/.well-known/aauth-person.json").status_code == 404
        assert client.post("/aauth/token", content=b"{}").status_code == 404
        server.append(World().ps)
        assert client.get("/.well-known/aauth-person.json").status_code == 200
        assert client.post("/aauth/token", content=b"{}").status_code == 401


def test_a_resolver_needs_the_endpoint_path():
    with pytest.raises(ValueError, match="resolver"):
        person_server_router(lambda request: None)
