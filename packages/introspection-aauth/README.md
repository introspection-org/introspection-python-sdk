# introspection-aauth

An AAuth Person Server and Access Server for Python, implementing
[draft-hardt-oauth-aauth-protocol -11](https://github.com/dickhardt/AAuth):
missions, person and auth tokens, budgets, approvals, and four-party
federation (`#access-server-federation`). You provide the store; nothing
here names a database, a queue or a web framework.

```bash
pip install introspection-aauth            # the servers
pip install 'introspection-aauth[fastapi]' # and FastAPI routers for them
```

## Layout

| Module | Holds |
| --- | --- |
| `introspection_aauth.protocol` | What both servers share, written once: `AAuthError`, a subclass per AAuth error code (`InvalidRequest`, `InvalidToken`, `InvalidCode`, …), and their problem+json; Ed25519 signing keys (current and previous) and Ed25519/ES256 verification; RFC 9421 signing and verification with `Signature-Key`; AAuth's tokens; discovery of metadata and keys, cached for a bounded time; budgets; and the server plumbing both use: the `Server` base, verifying an agent's or a server's signed request, the `202` pending answer, reading an R3 proposal. |
| `introspection_aauth.person_server` | `PersonServer`, its `Store` and `Directory` protocols, a `MemoryStore`, and `AccessServerClient`, its client for a resource's own Access Server. |
| `introspection_aauth.access_server` | `AccessServer`, its policy `Verdict`s, its `Store` protocol and a `MemoryStore`. |
| `introspection_aauth.fastapi` | `person_server_router` and `access_server_router`, and `*_well_known_router` for the documents alone (the `fastapi` extra). Each takes an `APIRouter` of yours for its tags, dependencies, responses or `include_in_schema`. |

Neither server imports the other, and `protocol` imports neither.

Every body either server sends or reads is a pydantic model in
`protocol.wire`, and every token's claims a model in `protocol.claims`
that checks what the token must be on its own: `exp` after `iat`, a
lifetime of at most an hour where the protocol caps it, a `cnf` that is a
public key, a budget of non-negative integers. Whether a token that
verified is the one a caller expected is an expectation's `failures`,
which names every check it fails (`["sub", "tenant"]`). Discovery reads
only AAuth server identifiers (`https://` and a lowercase host, nothing
more), requires an https `jwks_uri`, and follows no redirect. An agent's
request is signed `sig=jwt` and a server's `sig=jwks_uri`; any other scheme,
server or `dwk` is refused before anything is fetched. An R3 proposal is
read only from its resource's own https origin. An approved auth token is
collected once; a second poll is `410 invalid_code`.

## Dependencies

```
introspection-aauth
├── cryptography   Ed25519 and ES256, JWK thumbprints, PEM keys
├── http-sfv       RFC 9651 structured fields: Signature-Input, Signature, Signature-Key, AAuth-Requirement
├── httpx2         discovery, federation and R3 fetches
├── pydantic       models and request bodies
└── fastapi        (extra: fastapi) the routers
```

JWS is done here, on `cryptography`: AAuth's tokens use fully-specified
algorithms (`alg: Ed25519`, RFC 9864), and every claim check is the
protocol's own, so a JWT library would add nothing but a dependency.

## A Person Server

```python
import httpx2 as httpx
from introspection_aauth.fastapi import person_server_router
from introspection_aauth.person_server import MemoryStore, PersonServer
from introspection_aauth.protocol import SigningKey

person_server = PersonServer(
    "https://ps.example",
    SigningKey.from_pem(open("ps.pem").read()),
    MemoryStore(),
    subject_secret=b"...",                 # keys each person's directed `sub`
    agent_providers=["https://agents.example"],
    http=httpx.AsyncClient(),
    endpoint_base="https://ps.example/aauth",
    default_tenant="acme",
)
app.include_router(person_server_router(person_server))
# Or with your own router: its prefix is the start of the endpoint base's
# path, and the well-known documents are mounted at the root on their own.
#   app.include_router(person_server_router(person_server, APIRouter(prefix="/aauth", tags=["AAuth"])))
#   app.include_router(person_server_well_known_router(person_server))

# Your approval app answers what it asks:
await person_server.decide(tenant, approval_id, ApprovalStatus.APPROVED,
                           decided_by="dana", budget=Budget(amount=200_000, unit="USD", decimals=2))
```

`subject_secret` is separate from the signing key, so rotating the key
changes no one's identifier. Pass `previous_keys` to keep a rotated key
published until what it signed has expired.

## An Access Server

```python
def policy(request: AccessRequest) -> Verdict:
    if request.tenant == "acme":
        return Verdict.allow()              # or allow(scope=..., budget=...) for less
    return Verdict.approval()               # wait; settle it with decide()

access_server = AccessServer("https://as.example", key, policy,
                             resources=["https://booking.example"],
                             person_servers=["https://ps.example"],
                             agent_providers=["https://agents.example"],
                             http=httpx.AsyncClient())
app.include_router(access_server_router(access_server))
```

## Bring your own store

`person_server.Store` is the Person Server's state in logical operations,
named by their CRUD verb: `select_binding` and `insert_binding` (bind a key
to the first person it names), `select_mission`, `insert_mission`,
`update_spend` (spend only if it fits, atomically), `update_mission_log`,
`update_mission_end`, `select_approval`, `insert_approval`, and
`transition_approval`, which replaces an approval only if its status and
version have not changed. `transaction()` groups the writes that commit together: a decision
with the mission it creates or spends, and a federated auth token with the
spend it pays for. `transaction()` yields a store scoped to it; pass it as
`decide(..., store=tx)` to make a decision part of a unit of work of your
own, and call `decided` once that commits. Whether a store encrypts what it keeps is its own
choice. `access_server.Store` is `select_pending`, `insert_pending` and `transition_pending`.

## Durable federation

`PersonServer(on_federate=...)` is told of each approved request a
resource's Access Server must decide. Unset, `PersonServer.federate` drives
it in this process. A host with a durable executor journals the steps
itself: `federation_due`, `AccessServerClient.discover`, `.request`,
`record_federation`, wait `Outcome.poll_delay()`, `.poll`,
`record_federation`, and so on until `record_federation` returns False.

The server makes every call through the `httpx.AsyncClient` it is given, so
retrying a dropped connection is that client's: pass one with
`transport=httpx.AsyncHTTPTransport(retries=3)` to retry, or a mock transport
in tests.

## Not served

As in the hosted Person Server: `requirement=claims` and `clarification`,
payment (`402`, answered `403 denied`), step-up with an auth token,
sub-agents and call chaining (`subagent_token`, `upstream_token`), and
token revocation.

## Example

`examples/introspection_examples/aauth/four_party.py` runs the four-party
flow in one process:

```bash
cd examples && uv run -m introspection_examples.aauth.four_party
```
