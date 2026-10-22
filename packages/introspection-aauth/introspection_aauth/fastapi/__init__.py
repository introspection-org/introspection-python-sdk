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

from introspection_aauth.fastapi.access_server import (
    AccessServerResolver,
    access_server_router,
    access_server_well_known_router,
)
from introspection_aauth.fastapi.person_server import (
    PersonServerResolver,
    person_server_router,
    person_server_well_known_router,
)

__all__ = [
    "AccessServerResolver",
    "PersonServerResolver",
    "access_server_router",
    "access_server_well_known_router",
    "person_server_router",
    "person_server_well_known_router",
]
