# Introspection SDK Examples

## Setup

```bash
cd examples
uv sync
export INTROSPECTION_TOKEN=your-token
```

## REST API

```bash
uv run python -m introspection_examples.api.runtimes                 # Runner: tasks + files end-to-end (sync)
uv run python -m introspection_examples.api.async_runtimes           # AsyncRunner: same flow on asyncio
uv run python -m introspection_examples.api.repositories             # Repositories: list, browse contents, read a file, page commits
uv run python -m introspection_examples.api.conversation_atif        # Conversations: project one onto a Harbor ATIF trajectory, write trajectory.json
uv run python -m introspection_examples.api.members                  # Members: label one with metadata, list members by metadata
uv run python -m introspection_examples.api.automations              # Automations: list, schedule a one-off reminder, read trigger events
uv run python -m introspection_examples.api.connections              # Connections: list a member's connected apps, start connecting one
uv run python -m introspection_examples.api.connectors_slack         # Create a Slack connector and authorize a workspace
uv run python -m introspection_examples.api.connectors_pipedream     # Create a Pipedream connector and authorize one app
uv run python -m introspection_examples.api.connectors_custom_app    # Find a custom MCP app, discover OAuth, create + authorize with a binding
uv run python -m introspection_examples.api.service_account          # service_account Application: client_credentials token, then run a task
uv run python -m introspection_examples.api.native_email_code        # native Application: email-code sign-in for an end user (prompts for the code)
```

Each example's module docstring lists the environment it needs.

## Custom events

```bash
uv run python -m introspection_examples.otel.log_event               # log_event: log a custom-named event, read it back via introspection.track
```

## Docs reference snippets

The docs site extracts its reference-page snippets from the
`# #region docs:<id>` blocks in these modules at a pinned release tag; edit a
region together with the page it feeds.

```bash
uv run python -m introspection_examples.reference.python_run_task        # Python SDK page: run a task, stream it, send a follow-up
uv run python -m introspection_examples.reference.python_sdk             # Python SDK page: reattach, interrupts, cancel, files, reads, feedback
uv run python -m introspection_examples.reference.auth_api_key           # Authentication page: API key
uv run python -m introspection_examples.reference.auth_service_account   # Authentication page: service-account application
uv run python -m introspection_examples.reference.auth_hosted_login      # Authentication page: hosted-login code exchange (needs a live redirect)
```

`python_run_task` targets a runtime with the slug `support-agent`, as the docs
page does.

## Tracing

There are no tracing examples here. The Python SDK ships no framework
integrations: attach `IntrospectionSpanProcessor` to your provider and
instrument with any OTel-emitting library, or instrument manually. See
[`../docs/otel.md`](../docs/otel.md).

## Directory Structure

```
examples/introspection_examples/
  api/                 # REST API (IntrospectionClient, Runner, tasks, files)
  otel/                # OTel logs surface (log_event)
  reference/           # code behind the docs' reference-page snippets
```
