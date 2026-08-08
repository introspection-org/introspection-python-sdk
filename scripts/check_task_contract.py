#!/usr/bin/env python3
"""Compare this SDK's task surface against the published API reference.

This SDK sent `mode` on every `create()` call for the entire life of that
field's retirement: it defaulted to a non-None value, so it survived the request
builder's `if v is not None` filter and always went on the wire, into a create
body that declares `additionalProperties: false`. `Task.mode` and the `modes`
list filter went stale by the same mechanism at the same time. Nothing in CI
could catch any of it, because nothing in CI knew what the API accepted.

The reference at docs.introspection.dev is generated from the Data Plane API
itself, so comparing against it compares against the API's own declaration
rather than a second hand-maintained copy.

Four surfaces are checked, because `mode` went stale on three of them at once
and a create-body-only check would have caught one:

    TaskCreate       POST /v1/tasks body
    Task             the read model every task response returns
    TaskRunCreate    POST /v1/tasks/{id}/runs body
    list filters     GET /v1/tasks query parameters

Extra and missing fields do not mean the same thing on each, so they are not
reported the same way. See SURFACES.

Deliberately NOT a unit test and NOT a pull-request gate. It reaches the network
and it goes red when the API changes, which is a fact about the world and not
about the commit under review — wiring that into every PR would train people to
ignore it, and being ignorable is how the last one survived. It runs on a
schedule instead, where a red run means "the API moved, go look".

Run: python scripts/check_task_contract.py [--spec URL|PATH]
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

from introspection_sdk.runner_resources.tasks import Tasks
from introspection_sdk.schemas.tasks import (
    Task,
    TaskCreateRequest,
    TaskRunCreateRequest,
    TaskRunResumeRequest,
)

DEFAULT_SPEC = "https://docs.introspection.dev/openapi/dataplane.json"


def schema_properties(spec: dict, name: str) -> set[str]:
    return set(spec["components"]["schemas"][name].get("properties", {}))


def query_parameters(spec: dict, path: str, method: str) -> set[str]:
    return {
        p["name"] for p in spec["paths"][path][method].get("parameters", [])
    }


def list_signature() -> set[str]:
    return {p for p in inspect.signature(Tasks.list).parameters if p != "self"}


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
        # `repository_id` is retired from the public create body: the API
        # accepted it, stamped it into task metadata, and read it nowhere.
        # Exempted so the check stays green against a published reference
        # that still declares it; the stale-exemption rule fails once the
        # reference catches up, which is the prompt to delete this.
        exempt=frozenset({"runtime_id", "repository_id"}),
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
        # `message` was the legacy shorthand for `prompt.text`, retired in the
        # same cycle; the exemption self-clears as above.
        exempt=frozenset({"message"}),
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
        "--spec", default=DEFAULT_SPEC, help="OpenAPI URL or path"
    )
    args = parser.parse_args()

    try:
        spec = load_spec(args.spec)
    except Exception as error:  # noqa: BLE001 - any failure to read is fatal here
        print(
            f"could not read the API reference at {args.spec}: {error}",
            file=sys.stderr,
        )
        return 1

    problems: list[str] = []
    advisories: list[str] = []
    checked = 0

    for surface in SURFACES:
        try:
            server_fields = surface.server(spec)
        except KeyError as error:
            problems.append(f"{surface.name}: the reference has no {error}")
            continue

        sdk_fields = surface.sdk()
        checked += len(server_fields | sdk_fields)

        missing = server_fields - sdk_fields - surface.exempt
        extra = sdk_fields - server_fields
        stale_exemptions = surface.exempt - server_fields

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

        if lines:
            block = "\n".join([f"{surface.name} — {surface.where}", *lines])
            (problems if fatal else advisories).append(block)

    for block in advisories:
        print(f"note:\n{block}\n")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(f"\nreference: {args.spec}", file=sys.stderr)
        return 1

    print(
        f"✓ task surface matches the published reference ({len(SURFACES)} surfaces, {checked} fields)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
