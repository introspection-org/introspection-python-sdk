#!/usr/bin/env python3
"""Compare this SDK's request/response surface against the published API reference.

This SDK sent `mode` on every `create()` call for the entire life of that
field's retirement: it defaulted to a non-None value, so it survived the request
builder's `if v is not None` filter and always went on the wire, into a create
body that declares `additionalProperties: false`. `Task.mode` and the `modes`
list filter went stale by the same mechanism at the same time. Nothing in CI
could catch any of it, because nothing in CI knew what the API accepted.

The reference at docs.introspection.dev is generated from the Data Plane API
itself, so comparing against it compares against the API's own declaration
rather than a second hand-maintained copy.

Every request body, read model, and list-filter set this SDK declares is
checked, not just the task ones. `mode` went stale on three task surfaces at
once, so a create-body-only check would have caught one of three; restricting
the check to tasks has the same shape of blind spot one resource wider. Files,
shares, events, metrics, and the cancel body carry the same
`additionalProperties: false` hazard on their create bodies, and the event
envelope is shared by all six families, so one drift there moves all of them.

Extra and missing fields do not mean the same thing on each surface, so they
are not reported the same way. See SURFACES.

A `list`-style method's keyword surface is compared against the route's query
parameters. Kwargs that are resolved client-side and never sent — ergonomic
window aliases, the Arrow `format` switch — are declared in `client_side` so
they are not misreported as parameters the API rejects.

Deliberately NOT a unit test and NOT a pull-request gate. It reaches the network
and it goes red when the API changes, which is a fact about the world and not
about the commit under review — wiring that into every PR would train people to
ignore it, and being ignorable is how the last one survived. It runs on a
schedule instead, where a red run means "the API moved, go look".

Run: python scripts/check_api_contract.py [--spec URL|PATH]
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import urllib.request
from collections.abc import Callable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

from introspection_sdk.resources.experiments import Experiments
from introspection_sdk.resources.recipes import Recipes
from introspection_sdk.runner_resources.conversations import (
    ConversationItems,
    Conversations,
)
from introspection_sdk.runner_resources.events import Events
from introspection_sdk.runner_resources.files import Files
from introspection_sdk.runner_resources.shares import Shares
from introspection_sdk.runner_resources.tasks import Tasks
from introspection_sdk.schemas.events import FeedbackEvent
from introspection_sdk.schemas.files import File, FileUpdateRequest
from introspection_sdk.schemas.metrics import MetricQueryRequest
from introspection_sdk.schemas.shares import ResourceShare, ShareCreateRequest
from introspection_sdk.schemas.tasks import (
    Task,
    TaskCancelRequest,
    TaskCreateRequest,
    TaskRunCreateRequest,
    TaskRunResumeRequest,
)

DEFAULT_SPEC = "https://docs.introspection.dev/openapi/dataplane.json"
DEFAULT_CP_SPEC = "https://docs.introspection.dev/openapi/controlplane.json"


def schema_properties(spec: dict, name: str) -> set[str]:
    return set(spec["components"]["schemas"][name].get("properties", {}))


def query_parameters(spec: dict, path: str, method: str) -> set[str]:
    """Query parameters only.

    A templated route also declares its path segments as parameters, and
    counting those would report a path argument the caller passes positionally
    as a query parameter the SDK forgot.
    """
    return {
        p["name"]
        for p in spec["paths"][path][method].get("parameters", [])
        if p.get("in") == "query"
    }


def signature_params(method: Callable[..., object]) -> set[str]:
    """Keyword surface of a `list`-style method, minus `self`."""
    return {p for p in inspect.signature(method).parameters if p != "self"}


def list_signature() -> set[str]:
    return signature_params(Tasks.list)


@dataclass(frozen=True)
class Surface:
    name: str
    where: str
    sdk: Callable[[], set[str]]
    server: Callable[[dict], set[str]]
    # Fields the API has that this SDK omits deliberately. Checked for staleness
    # in both directions: an exemption naming a field the API no longer has is
    # itself reported, so it cannot quietly outlive its reason.
    exempt: frozenset[str] = frozenset()
    # Method kwargs that are resolved client-side and never sent as query
    # params (ergonomic window aliases, response-format switches). Without
    # this the check reports them as params the API rejects, which is exactly
    # backwards: they are never sent, so the API never sees them.
    client_side: frozenset[str] = frozenset()
    # Which reference declares this surface. The two planes are separate
    # services with separate specs, and the CP half went unchecked entirely
    # until an experiments filter the API does not accept shipped in two SDKs.
    plane: str = "dp"
    extra_is_fatal: bool = True
    missing_is_fatal: bool = True
    extra_means: str = ""
    missing_means: str = ""
    notes: tuple[str, ...] = field(default=())


SURFACES = (
    Surface(
        name="TaskCreate",
        where="POST /v1/tasks body",
        sdk=lambda: set(TaskCreateRequest.model_fields),
        server=lambda spec: schema_properties(spec, "TaskCreate"),
        # Runner-bound client: the credential's claim is authoritative for
        # runtime selection and the API ignores a body runtime_id from such a
        # caller, so exposing it would be a field that silently does nothing.
        exempt=frozenset({"runtime_id"}),
        extra_means="rejected with a 422 — the create body forbids undeclared fields",
        missing_means="cannot be sent by callers of this SDK",
    ),
    Surface(
        name="Task",
        where="the task read model",
        sdk=lambda: set(Task.model_fields),
        server=lambda spec: schema_properties(spec, "Task"),
        extra_means="invented — the API does not return it, so the SDK describes a response that no longer exists",
        missing_means="returned by the API but not surfaced by this SDK",
    ),
    Surface(
        name="TaskRunCreate",
        where="POST /v1/tasks/{id}/runs body",
        # The SDK splits one wire body into a create request and a resume
        # request; the API declares them as one schema.
        sdk=lambda: set(TaskRunCreateRequest.model_fields)
        | set(TaskRunResumeRequest.model_fields),
        server=lambda spec: schema_properties(spec, "TaskRunCreate"),
        exempt=frozenset(),
        extra_means="sent but not declared by the API",
        missing_means="cannot be sent by callers of this SDK",
    ),
    Surface(
        name="list filters",
        where="GET /v1/tasks query parameters",
        sdk=list_signature,
        server=lambda spec: query_parameters(spec, "/v1/tasks", "get"),
        # runtime_id/runtime_ids/updated_after/conversation_id are product-UI
        # shaped; identity_key is privileged-only and 403s for the credentials
        # this SDK carries. Which filters to expose is a product decision, so
        # absence here is reported and does not fail.
        exempt=frozenset(
            {
                "runtime_id",
                "runtime_ids",
                "updated_after",
                "conversation_id",
                "identity_key",
            }
        ),
        missing_is_fatal=False,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # --- files -------------------------------------------------------------
    Surface(
        name="File",
        where="the file read model",
        sdk=lambda: set(File.model_fields),
        server=lambda spec: schema_properties(spec, "File"),
        extra_means="invented — the API does not return it",
        missing_means="returned by the API but not surfaced here",
    ),
    Surface(
        name="FileUpdate",
        where="PATCH /v1/files/{id} body",
        sdk=lambda: set(FileUpdateRequest.model_fields),
        server=lambda spec: schema_properties(spec, "FileUpdate"),
        extra_means="sent but not declared by the API",
        missing_means="cannot be sent by callers of this SDK",
    ),
    Surface(
        name="file list filters",
        where="GET /v1/files query parameters",
        sdk=lambda: signature_params(Files.list),
        server=lambda spec: query_parameters(spec, "/v1/files", "get"),
        # `identity_key` is privileged-only and 403s for these credentials;
        # `task_id`/`share_id` are scoping params the runner already carries.
        exempt=frozenset({"identity_key", "task_id", "share_id"}),
        missing_is_fatal=False,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # --- shares ------------------------------------------------------------
    Surface(
        name="ShareCreate",
        where="POST /v1/shares body",
        sdk=lambda: set(ShareCreateRequest.model_fields),
        server=lambda spec: schema_properties(spec, "ShareCreate"),
        extra_means="sent but not declared by the API",
        missing_means="cannot be sent by callers of this SDK",
    ),
    Surface(
        name="ResourceShare",
        where="the share read model",
        sdk=lambda: set(ResourceShare.model_fields),
        server=lambda spec: schema_properties(spec, "ResourceShare"),
        extra_means="invented — the API does not return it",
        missing_means="returned by the API but not surfaced here",
    ),
    Surface(
        name="share list filters",
        where="GET /v1/shares query parameters",
        sdk=lambda: signature_params(Shares.list),
        server=lambda spec: query_parameters(spec, "/v1/shares", "get"),
        missing_is_fatal=False,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # --- events ------------------------------------------------------------
    Surface(
        name="event envelope",
        where="the common envelope on every event family",
        # One family stands in for all six: the envelope is shared, so a field
        # added or dropped there moves on every family at once. Checking one is
        # the same check six times; checking the payloads is a different check
        # and belongs to whichever family owns it.
        sdk=lambda: set(FeedbackEvent.model_fields),
        server=lambda spec: schema_properties(spec, "FeedbackEvent"),
        extra_means="invented — the API does not return it",
        missing_means="returned by the API but not surfaced here",
    ),
    Surface(
        name="event list filters",
        where="GET /v1/events query parameters",
        sdk=lambda: signature_params(Events.list),
        server=lambda spec: query_parameters(spec, "/v1/events", "get"),
        # Product-UI-shaped filters this SDK does not surface; `event_id` is
        # covered by `Events.get`.
        exempt=frozenset(
            {
                "event_id",
                "owner_key",
                "runtime_group_unattributed",
                "runtime_group_id",
                "conversation_ids",
                "trace_id",
                "span_id",
            }
        ),
        # `order`/`start`/`end`/`lookback` are the ergonomic window inputs,
        # resolved into `direction`/`start_date`/`end_date` before the request
        # is built; `format` selects Arrow via the Accept header, not a param.
        client_side=frozenset({"order", "start", "end", "lookback", "format"}),
        missing_is_fatal=False,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # --- conversations -----------------------------------------------------
    # There is deliberately no `Conversation` read-model surface: the published
    # reference declares no properties for that schema, so the comparison would
    # pass by doing nothing. The list filters are declared, so they are checked.
    Surface(
        name="conversation list filters",
        where="GET /v1/conversations query parameters",
        sdk=lambda: signature_params(Conversations.list),
        server=lambda spec: query_parameters(spec, "/v1/conversations", "get"),
        # Product-UI-shaped filters this SDK does not surface.
        exempt=frozenset(
            {
                "conversation_ids",
                "owner_key",
                "resolution",
                "sentiment",
                "share_id",
            }
        ),
        # `order`/`start`/`end`/`lookback` are ergonomic window inputs resolved
        # into `direction`/`start_date`/`end_date`; `format` selects Arrow via
        # the Accept header rather than a query parameter.
        client_side=frozenset({"order", "start", "end", "lookback", "format"}),
        missing_is_fatal=False,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # The export route needs its own surface. Widening the check to 15 surfaces
    # still left every route this SDK had just *gained* unchecked, so the
    # conversation export shipped without `start_date`/`end_date` and nothing
    # noticed: a guard that covers only what already existed goes blind exactly
    # where new code lands.
    Surface(
        name="conversation export filters",
        where="GET /v1/conversations/{id}/export query parameters",
        sdk=lambda: signature_params(Conversations.export_trajectory),
        # `conversation_id` is the path segment, passed positionally.
        client_side=frozenset({"conversation_id"}),
        server=lambda spec: query_parameters(
            spec, "/v1/conversations/{conversation_id}/export", "get"
        ),
        missing_is_fatal=True,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # The items route is where the ordering bug hid: this SDK declared an
    # `order` the route never accepted and omitted the window/share params it
    # did, and no surface covered it. A sub-resource is still a route.
    Surface(
        name="conversation item list filters",
        where="GET /v1/conversations/{id}/items query parameters",
        sdk=lambda: signature_params(ConversationItems.list),
        # `conversation_id` is the path segment, passed positionally.
        client_side=frozenset({"conversation_id"}),
        server=lambda spec: query_parameters(
            spec, "/v1/conversations/{conversation_id}/items", "get"
        ),
        missing_is_fatal=True,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # --- control plane -----------------------------------------------------
    Surface(
        name="experiment list filters",
        where="GET /v1/experiments query parameters",
        plane="cp",
        sdk=lambda: signature_params(Experiments.list),
        server=lambda spec: query_parameters(spec, "/v1/experiments", "get"),
        # The deprecated spelling of `project`; this SDK sends the current one.
        exempt=frozenset({"project_id"}),
        missing_is_fatal=False,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    Surface(
        name="recipe list filters",
        where="GET /v1/recipes query parameters",
        plane="cp",
        sdk=lambda: signature_params(Recipes.list),
        server=lambda spec: query_parameters(spec, "/v1/recipes", "get"),
        exempt=frozenset({"project_id"}),
        missing_is_fatal=False,
        extra_means="sent as a query parameter the API does not accept",
        missing_means="accepted by the API but not exposed here",
    ),
    # --- metrics -----------------------------------------------------------
    Surface(
        name="MetricQueryRequest",
        where="POST /v1/metrics body",
        sdk=lambda: set(MetricQueryRequest.model_fields),
        server=lambda spec: schema_properties(spec, "MetricQueryRequest"),
        extra_means="sent but not declared by the API",
        missing_means="cannot be sent by callers of this SDK",
    ),
    # --- task cancel -------------------------------------------------------
    Surface(
        name="TaskCancelRequest",
        where="POST /v1/tasks/{id}/runs/{rid}/cancel body",
        sdk=lambda: set(TaskCancelRequest.model_fields),
        server=lambda spec: schema_properties(spec, "TaskCancelRequest"),
        extra_means="sent but not declared by the API",
        missing_means="cannot be sent by callers of this SDK",
    ),
)


def load_spec(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as response:  # noqa: S310
            return json.load(response)
    return json.loads(Path(source).read_text())


def report(lines: list[str], heading: str, fields: AbstractSet[str]) -> None:
    """Accepts any set: exemptions are frozen, the computed differences are not."""
    lines.append(f"  {heading}")
    for name in sorted(fields):
        lines.append(f"      {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec", default=DEFAULT_SPEC, help="Data-Plane OpenAPI URL or path"
    )
    parser.add_argument(
        "--cp-spec",
        default=DEFAULT_CP_SPEC,
        help="Control-Plane OpenAPI URL or path",
    )
    args = parser.parse_args()

    specs: dict[str, dict] = {}
    for plane, source in (("dp", args.spec), ("cp", args.cp_spec)):
        try:
            specs[plane] = load_spec(source)
        except Exception as error:  # noqa: BLE001 - any failure to read is fatal
            print(
                f"could not read the API reference at {source}: {error}",
                file=sys.stderr,
            )
            return 1

    problems: list[str] = []
    advisories: list[str] = []
    checked = 0

    for surface in SURFACES:
        try:
            server_fields = surface.server(specs[surface.plane])
        except KeyError as error:
            problems.append(f"{surface.name}: the reference has no {error}")
            continue

        sdk_fields = surface.sdk()
        checked += len(server_fields | sdk_fields)

        missing = server_fields - sdk_fields - surface.exempt
        extra = sdk_fields - server_fields - surface.client_side
        stale_exemptions = surface.exempt - server_fields
        stale_client_side = surface.client_side - sdk_fields

        lines: list[str] = []
        fatal = False

        if extra:
            report(
                lines,
                f"sent/declared here but not by the API ({surface.extra_means}):",
                extra,
            )
            fatal = fatal or surface.extra_is_fatal
        if missing:
            report(
                lines,
                f"in the API but not here ({surface.missing_means}):",
                missing,
            )
            fatal = fatal or surface.missing_is_fatal
        if stale_exemptions:
            report(
                lines,
                "exempted here but no longer in the API (drop the exemption):",
                stale_exemptions,
            )
            fatal = True
        if stale_client_side:
            report(
                lines,
                "declared client-side here but no longer a parameter (drop it):",
                stale_client_side,
            )
            fatal = True

        if lines:
            block = "\n".join([f"{surface.name} — {surface.where}", *lines])
            (problems if fatal else advisories).append(block)

    for block in advisories:
        print(f"note:\n{block}\n")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(f"\nreference: {args.spec} + {args.cp_spec}", file=sys.stderr)
        return 1

    print(
        f"✓ SDK surface matches the published reference ({len(SURFACES)} surfaces, {checked} fields)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
