"""The Person Server's side of four-party access (`#access-server-federation`).

A resource token whose `aud` is the resource's own Access Server is redeemed
there: the Person Server signs as itself (`#ps-to-as-token-request`), follows
the deferred loop (`#deferred-responses`), and checks the auth token before
the agent gets it (`#auth-token-delivery`).

The loop is steps a host can journal: `PersonServer.federation_due`, then
`discover`, `request`, `PersonServer.record_federation`, wait `poll_delay`,
`poll`, `record_federation`, and so on; `PersonServer.federate` is that loop
in-process.
"""

from urllib.parse import urljoin

import httpx2 as httpx
from pydantic import ValidationError

from introspection_aauth.person_server.models import Federation, Outcome, Step
from introspection_aauth.protocol import jwt
from introspection_aauth.protocol.claims import (
    ACCESS_DWK,
    AgentTokenClaims,
    AuthTokenClaims,
    DeliveryExpectation,
    PersonTokenClaims,
    ResourceTokenClaims,
)
from introspection_aauth.protocol.discovery import Discovery
from introspection_aauth.protocol.errors import Problem, VerificationError
from introspection_aauth.protocol.keys import Jwks
from introspection_aauth.protocol.server import (
    Clock,
    Identity,
    https_endpoint,
    requirement_name,
    retry_after,
    same_origin,
)
from introspection_aauth.protocol.wire import (
    AccessServerMetadata,
    AuthTokenAnswer,
    TokenRequest,
)

SERVED = frozenset({"approval", "interaction"})
#: Requirements draft -11 defines that this Person Server does not serve.
NOT_SERVED = frozenset({"claims", "clarification"})


Metadata = AccessServerMetadata


class AccessServerClient:
    """Talks to the Access Server a verified resource token names, signed as the Person Server."""

    def __init__(
        self,
        identity: Identity,
        discovery: Discovery,
        http: httpx.AsyncClient,
        clock: Clock,
    ):
        self._identity = identity
        self._discovery = discovery
        self._http = http
        self._clock = clock

    async def discover(self, access_server: str) -> Metadata | Outcome:
        """`{aud}/.well-known/aauth-access.json`, whose `issuer` is the `aud`."""
        try:
            document = await self._discovery.get(
                f"{access_server}/.well-known/{ACCESS_DWK}",
                AccessServerMetadata,
            )
        except VerificationError as exc:
            return Outcome.unreachable(
                f"its metadata could not be read: {exc.detail}"
            )
        if document.issuer != access_server:
            return Outcome.unreachable("its metadata names another issuer")
        if not (
            https_endpoint(document.auth_token_endpoint)
            and same_origin(document.auth_token_endpoint, access_server)
            and same_origin(document.jwks_uri, access_server)
        ):
            return Outcome.unreachable(
                "its metadata keeps its auth_token_endpoint and jwks_uri "
                "off its own https origin"
            )
        return document

    async def request(
        self, federation: Federation, agent_jkt: str, metadata: Metadata
    ) -> Outcome:
        """The token request, with the budget the Person Server allows."""
        body = TokenRequest(
            resource_token=federation.resource_token,
            agent_token=federation.agent_token,
            presented_token=federation.presented_token,
            budget=federation.budget,
        ).to_json()
        url = metadata.auth_token_endpoint
        headers = self._identity.signed("POST", url, body, self._clock())
        response = await self._http.post(
            url, content=body, headers=headers, follow_redirects=False
        )
        return await self._outcome(
            response, url, federation, agent_jkt, metadata
        )

    async def poll(
        self,
        location: str,
        federation: Federation,
        agent_jkt: str,
        metadata: Metadata,
    ) -> Outcome:
        headers = self._identity.signed("GET", location, None, self._clock())
        response = await self._http.get(
            location, headers=headers, follow_redirects=False
        )
        return await self._outcome(
            response, location, federation, agent_jkt, metadata
        )

    async def _outcome(  # noqa: PLR0911
        self,
        response: httpx.Response,
        requested: str,
        federation: Federation,
        agent_jkt: str,
        metadata: Metadata,
    ) -> Outcome:
        status = response.status_code
        if status == 200:
            try:
                answer = AuthTokenAnswer.model_validate_json(response.content)
            except ValidationError:
                return Outcome.unreachable(
                    "it answered 200 without an auth_token"
                )
            return await self._delivered(
                answer.auth_token, federation, agent_jkt, metadata
            )
        if status == 202:
            return self._waiting(response, requested)
        if status == 402:
            return Outcome.refused(
                403,
                "denied",
                "the Access Server asks for payment, which this Person Server does not make",
            )
        if status in (429, 503):
            # Slow down and ask again: poll again, or send the request again.
            retry = retry_after(response.headers) or 0
            return Outcome(
                step=Step.PENDING,
                location=None
                if requested == metadata.auth_token_endpoint
                else requested,
                requirement=federation.requirement or "requirement=approval",
                retry_after=retry + 5 if status == 429 else retry,
            )
        try:
            problem = Problem.model_validate_json(response.content)
        except ValidationError:
            problem = None
        if 400 <= status < 500 and problem is not None and problem.error:
            return Outcome.refused(
                status,
                problem.error,
                f"the Access Server refused: {problem.detail or problem.error}",
            )
        return Outcome.unreachable(f"it answered {status}")

    @staticmethod
    def _waiting(response: httpx.Response, requested: str) -> Outcome:
        header = response.headers.get("aauth-requirement")
        requirement = requirement_name(header) if header else "approval"
        if requirement is None:
            return Outcome.unreachable("its AAuth-Requirement is malformed")
        if requirement in NOT_SERVED:
            return Outcome.refused(
                403,
                "denied",
                f"the Access Server asks for requirement={requirement}, not served here",
            )
        location = response.headers.get("location")
        polled = urljoin(requested, location) if location else None
        if polled is None or not same_origin(polled, requested):
            return Outcome.unreachable(
                "its pending Location is not on its own origin"
            )
        return Outcome(
            step=Step.PENDING,
            location=polled,
            # An unrecognised requirement is polled through, and relayed as approval.
            requirement=header
            if header and requirement in SERVED
            else "requirement=approval",
            retry_after=retry_after(response.headers),
        )

    async def _delivered(
        self,
        auth_token: str,
        federation: Federation,
        agent_jkt: str,
        metadata: Metadata,
    ) -> Outcome:
        """`#auth-token-delivery`, and the budget granted no more than was sent."""
        try:
            rt = ResourceTokenClaims.model_validate(
                jwt.decode(federation.resource_token).claims
            )
            presented = PersonTokenClaims.model_validate(
                jwt.decode(federation.presented_token).claims
            )
            agent = AgentTokenClaims.model_validate(
                jwt.decode(federation.agent_token).claims
            )
        except (VerificationError, ValidationError):
            return Outcome.unreachable(
                "its request's tokens cannot be read back"
            )
        try:
            keys = await self._discovery.get(metadata.jwks_uri, Jwks)
            claims = jwt.verify(
                auth_token,
                keys,
                jwt.AUTH_TOKEN,
                self._clock(),
                AuthTokenClaims,
            )
        except VerificationError as exc:
            return Outcome.unreachable(
                f"its auth token does not verify: {exc.detail}"
            )
        wrong = DeliveryExpectation(
            issuer=metadata.issuer,
            ps=self._identity.issuer,
            rt=rt,
            agent_jkt=agent_jkt,
            not_after=min(presented.exp, agent.exp),
            sent=federation.budget,
        ).failures(claims)
        if wrong:
            return Outcome.unreachable(
                f"its auth token has the wrong {', '.join(wrong)}"
            )
        return Outcome(
            step=Step.ISSUED,
            auth_token=auth_token,
            auth_token_expires_at=claims.exp,
            granted=claims.budget,
        )
