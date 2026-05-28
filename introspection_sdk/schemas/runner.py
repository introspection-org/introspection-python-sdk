"""Pydantic mirrors of CP `/v1/runtimes/{id}/run` and
`/v1/experiments/{id}/run` request/response models.

Wire fields are snake_case verbatim. Unknown fields are tolerated
via ``extra="allow"``.

The customer-facing :class:`RunnerSpec` is intentionally narrow —
sandbox-internal fields (``credentials`` for ext_proc egress, the
``bootstrap`` repo manifest, DP ``limits``, and the any-llm
``llm_proxy`` descriptor) live on ``InternalRunnerSpec`` on the
CP→DP internal route. See ``introspection-cloud/docs/design/sdk-api.md``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RunnerIdentity(_ApiModel):
    user_id: str | None = None
    anonymous_id: str | None = None
    conversation_id: str | None = None


class RunCallerLibrary(_ApiModel):
    """SDK / library identifier on a :class:`RunCaller`."""

    name: str | None = None
    version: str | None = None


class RunCallerPage(_ApiModel):
    """Page-context fields on a :class:`RunCaller`."""

    path: str | None = None
    referrer: str | None = None
    search: str | None = None
    title: str | None = None
    url: str | None = None


class RunCaller(_ApiModel):
    """Optional segment.io-style observability payload on
    :class:`RunRequest`.

    Used by CP for telemetry and experiment-report slicing only —
    **routing never reads ``caller``**. Arm picks walk ``identity.*``
    via ``hash_key_fields`` only. Mixing the two would be a privacy
    + stability footgun (e.g. routing on IP).

    Unknown fields ride along verbatim via ``extra="allow"``.
    """

    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    library: RunCallerLibrary | None = None
    page: RunCallerPage | None = None


class RunRequest(_ApiModel):
    """Body of ``POST /v1/{runtimes|experiments}/{id}/run``.

    Stashed on a Runner for ``refresh()``. Renamed from
    ``RuntimeContext`` — that's still importable as a deprecation
    alias for one release.
    """

    identity: RunnerIdentity | None = None
    caller: RunCaller | None = None
    ttl_seconds: int | None = None
    recipe_id: UUID | None = None


# Deprecated aliases — kept for one release. Prefer :class:`RunRequest`.
RunOptions = RunRequest
RuntimeContext = RunRequest


class RunnerRecipeSummary(_ApiModel):
    repository_id: UUID | None = None
    git_ref: str | None = None
    git_commit_sha: str | None = None


class RunnerContext(_ApiModel):
    runtime_id: UUID | None = None
    experiment_id: UUID | None = None
    recipe_id: UUID | None = None
    recipe: RunnerRecipeSummary | None = None
    arm_label: str | None = None
    identity: RunnerIdentity | None = None
    # Echoed from the request body when supplied.
    caller: RunCaller | None = None


class RunnerDeployment(_ApiModel):
    """DP deployment descriptor on a :class:`RunnerSpec`.

    Identifies the data-plane the customer should call into for this
    session: the externally reachable ``endpoint`` URL plus the CP
    ``slug`` / ``region`` for telemetry and routing diagnostics.
    """

    endpoint: str
    slug: str
    region: str


class RunnerSpec(_ApiModel):
    """Response body of CP ``/v1/{runtimes|experiments}/{id}/run`` —
    the customer wire.

    Sandbox-internal fields (``credentials``, ``bootstrap``, ``limits``,
    ``llm_proxy``) live on ``InternalRunnerSpec`` on the CP→DP internal
    route — never returned to customer callers.

    The customer's only credential is ``session_token`` — an RS256
    ``session_locator`` JWT. The DP server materializes the real
    access token from the session lookup on each request.
    """

    session_id: str
    deployment: RunnerDeployment
    session_token: str
    expires_at: datetime
    runtime_context: RunnerContext


__all__ = [
    "RunCaller",
    "RunCallerLibrary",
    "RunCallerPage",
    "RunOptions",  # deprecated alias for RunRequest
    "RunRequest",
    "RunnerContext",
    "RunnerDeployment",
    "RunnerIdentity",
    "RunnerRecipeSummary",
    "RunnerSpec",
    "RuntimeContext",  # deprecated alias for RunRequest
]
