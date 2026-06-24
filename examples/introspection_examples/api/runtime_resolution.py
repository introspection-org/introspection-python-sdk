"""Runtime resolution modes + yank walkthrough — Python sibling of the
Node ``examples/api/runtime-resolution.ts`` example.

Demonstrates how a runtime group decides which runtime serves a run, and how
to withdraw ("yank") a bad runtime so it stops being resolved as the active
one for an environment:

  - ``sticky`` (production default): a run pins the runtime active when it
    started and keeps it for the whole conversation, even after a newer
    runtime is promoted.
  - ``latest`` (non-prod default): every run resolves the currently active
    runtime for the environment.

Yanking is the safety valve: a yanked runtime never resolves as active, so new
runs fall back to the previous active runtime (or "none active" until a
replacement is promoted). In-flight sticky runs keep using it.

Run with:
    INTROSPECTION_TOKEN=intro_xxx

        uv run python -m introspection_examples.api.runtime_resolution

Optional env:
    INTROSPECTION_RUNTIME_NAME  - runtime to resolve (default: customer-agent)
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)

The project is scoped by the API key — there is no client-level project
option or env override.
"""

from __future__ import annotations

import os

from introspection_sdk import IntrospectionClient


def main() -> None:
    client = IntrospectionClient()

    runtime_name = os.getenv("INTROSPECTION_RUNTIME_NAME", "customer-agent")

    # 1) Resolve what's currently serving production. resolve_by_name only
    #    matches active, non-yanked runtimes.
    active = client.runtimes.resolve_by_name(runtime_name)
    suffix = (
        f" — YANKED: {active.yanked_reason or ''}" if active.yanked_at else ""
    )
    print(f"active production runtime: {active.name} ({active.id}){suffix}")

    # 2) List the production candidates for this group, newest first, omitting
    #    any that have been withdrawn.
    eligible = [
        f"{rt.name} ({rt.id})"
        for rt in client.runtimes.list(
            environment="production",
            exclude_yanked=True,
            limit=10,
        )
    ]
    print("eligible production runtimes:\n  " + "\n  ".join(eligible))

    # 3) Suppose the active runtime is misbehaving in production. Yank it: new
    #    runs immediately stop resolving it and fall back to the prior active
    #    runtime; conversations already pinned to it (sticky) finish unharmed.
    yanked = client.runtimes.yank(
        active.id,
        reason="regression in tool-call formatting — rolling back",
    )
    print(
        f"yanked {yanked.name} at {yanked.yanked_at}: {yanked.yanked_reason}"
    )

    # 4) Re-resolve — the group now points production at the previous runtime,
    #    or raises LookupError if nothing else is active for the environment.
    try:
        fallback = client.runtimes.resolve_by_name(runtime_name)
        print(f"production now resolves to: {fallback.name} ({fallback.id})")
    except LookupError:
        print(
            "no active runtime for production — promote a replacement "
            "before new runs can start"
        )

    # 5) If the yank was a mistake, reverse it; the runtime is eligible again.
    restored = client.runtimes.unyank(active.id)
    print(f"restored {restored.name}; yanked_at={restored.yanked_at}")


if __name__ == "__main__":
    main()
