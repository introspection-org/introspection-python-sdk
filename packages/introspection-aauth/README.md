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
| `introspection_aauth.protocol` | What both servers share, written once: `AAuthError` and its problem+json; Ed25519 signing keys (current and previous) and Ed25519/ES256 verification; RFC 9421 signing and verification with `Signature-Key`; AAuth's tokens; discovery of metadata and keys, cached for a bounded time; budgets; and the server plumbing both use: the `Server` base, verifying an agent's or a server's signed request, the `202` pending answer, reading an R3 proposal. |
| `introspection_aauth.person_server` | `PersonServer`, its `Store` and `Directory` protocols, a `MemoryStore`, and `federation`: the client for a resource's Access Server and the loop around it. |
| `introspection_aauth.access_server` | `AccessServer`, its policy `Verdict`s, its `Store` protocol and a `MemoryStore`. |
| `introspection_aauth.fastapi` | `person_server_router` and `access_server_router`, and `*_well_known_router` for the documents alone (the `fastapi` extra). Each takes an `APIRouter` of yours for its tags, dependencies, responses or `include_in_schema`. |

Neither server imports the other, and `protocol` imports neither.

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

`person_server.Store` is the Person Server's state in logical operations:
bind an agent key to a person, read and insert missions, spend from a
mission only if it fits (atomically), log and end missions, read and save
approvals, and replace an approval only if its status and version have not
changed. `transaction()` groups the writes that commit together: a decision
with the mission it creates or spends, and a federated auth token with the
spend it pays for. Whether a store encrypts what it keeps is its own
choice. `access_server.Store` is three methods over pending requests.

## Durable federation

`PersonServer(on_federate=...)` is told of each approved request a
resource's Access Server must decide. Unset, `federation.run` drives it in
this process. A host with a durable executor journals the steps itself:
`federation.due`, `AccessServerClient.discover`, `.request`,
`federation.record`, wait `federation.poll_delay`, `.poll`, `record`, and so
on until `record` returns False.

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
