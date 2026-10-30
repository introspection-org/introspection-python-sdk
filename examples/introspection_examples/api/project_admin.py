"""Administer a project: who you are, its API keys and runtime settings.

Reads the signed-in member and organization, the org's projects, a
project's API keys, credentials, variables, judges, endpoints and runtime
peerings, and mints
the member's own short-lived access token for the project; then, when
INTROSPECTION_ADMIN_WRITE=1, mints an API key, saves its one-time plaintext,
acknowledges it and revokes it again, renames an endpoint and back, creates
and deletes another, and creates, renames and deletes a sibling project on the same deployment.

These routes need an org credential: an owner's or admin's Control Plane
session (or an access token minted for one). A project API key carries none
of their scopes and gets a 403, so the example reads
INTROSPECTION_CP_SESSION rather than INTROSPECTION_TOKEN. Without it, or
without INTROSPECTION_PROJECT, it prints a skip message and exits 0, so the
examples workflow can list it whether or not a session is configured.

Run with:
    INTROSPECTION_CP_SESSION=...   # the intro_cp_session cookie value
    INTROSPECTION_PROJECT=support  # project slug or id

        uv run python -m introspection_examples.api.project_admin

Optional env:
    INTROSPECTION_ADMIN_WRITE   - 1 to also mint and revoke an API key
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from introspection_sdk import IntrospectionClient
from introspection_sdk.schemas.lanes import Environment


def main() -> None:
    load_dotenv()
    session = os.getenv("INTROSPECTION_CP_SESSION")
    project = os.getenv("INTROSPECTION_PROJECT")
    if not session or not project:
        print(
            "skipping: set INTROSPECTION_CP_SESSION to an owner's Control "
            "Plane session and INTROSPECTION_PROJECT to a project slug or id "
            "to run this example",
            file=sys.stderr,
        )
        return

    client = IntrospectionClient(cp_session=session)
    try:
        # #region docs:project-admin
        me = client.oidc.me()
        print(f"signed in as member {me.member_id} of org {me.org_id}")
        org = client.organizations.me()
        print(f"organization {org.slug}: {org.name}")

        for each in client.projects.list():
            print(f"  project {each.slug or each.id}: {each.name}")

        # `project` names the project on every project-scoped call, since a
        # member session names none of its own.
        for key in client.api_keys.list(project=project):
            print(f"  key {key.key_display} {key.status} {key.environment}")
        for credential in client.credentials.list(project=project):
            print(
                f"  credential {credential.name} {credential.secret_display}"
            )
        for variable in client.variables.list(project=project):
            print(f"  variable {variable.name}={variable.value}")
        for judge in client.judges.list(project=project):
            print(f"  judge {judge.name} sample_rate={judge.sample_rate}")
        for endpoint in client.endpoints.list(project=project):
            print(
                f"  endpoint {endpoint.name} {endpoint.kind} {endpoint.host}"
            )
        # Runtime groups the project offers other projects, then the ones
        # other projects offer it. Peerings are written in the web app.
        for peering in client.projects.peerings.list(project):
            print(f"  offers runtime group {peering.runtime_group_id}")
        for peering in client.projects.peerings.list(project, granted=True):
            print(f"  granted runtime group {peering.runtime_group_id}")
        # #endregion docs:project-admin

        # #region docs:project-token
        # The member's own Data Plane token for the project, with the
        # member's scopes there (such as `git:push`, which no service
        # account holds). A SecretStr: printing it shows **********.
        minted = client.tokens.create(project=project, expires_minutes=15)
        print(f"minted a project token until {minted.expires_at}")
        member = IntrospectionClient(
            token=minted.access_token.get_secret_value()
        )
        try:
            print(f"  as the member: {len(member.repositories.list())} repos")
        finally:
            member.shutdown()
        # #endregion docs:project-token

        if os.getenv("INTROSPECTION_ADMIN_WRITE") == "1":
            # #region docs:api-key-rotate
            created = client.api_keys.create(
                project=project,
                name="example",
                environment=Environment.DEVELOPMENT,
            )
            # A SecretStr: printing `created` shows **********. This is the
            # only time the API returns the plaintext.
            plaintext = (
                created.api_key.get_secret_value() if created.api_key else ""
            )
            print(f"minted {created.key_display} ({len(plaintext)} chars)")
            client.api_keys.acknowledge(created.id, project=project)
            # `expires_in` keeps the key working that long, for a rotation.
            client.api_keys.delete(created.id, project=project, expires_in=0)
            # #endregion docs:api-key-rotate

            # #region docs:endpoint-edit
            endpoints = client.endpoints.list(project=project).page().records
            if endpoints:
                endpoint = client.endpoints.get(
                    endpoints[0].id, project=project
                )
                client.endpoints.update(
                    endpoint.id,
                    project=project,
                    name=f"{endpoint.name}-renamed",
                )
                client.endpoints.update(
                    endpoint.id, project=project, name=endpoint.name
                )
                print(f"renamed endpoint {endpoint.name} and back")
            # `client.endpoints.delete(endpoint.id, project=project)` removes
            # one; an MCP server's endpoint comes back with its connection.
            api = client.endpoints.create(
                project=project,
                name="example-api",
                host="example-api.example.com",
                kind="api",
            )
            client.endpoints.delete(api.id, project=project)
            # #endregion docs:endpoint-edit

            # #region docs:project-lifecycle
            # A new project lives on a Data Plane deployment; this one takes
            # the deployment of the project it sits beside.
            home = client.projects.get(project)
            sibling = client.projects.create(
                name=f"{home.name} (example)",
                slug=f"{home.slug or home.id}-example",
                deployment_id=home.deployment_id,
            )
            client.projects.update(
                sibling.id, description="made by an example"
            )
            client.projects.delete(sibling.id)
            print(f"created and deleted project {sibling.slug}")
            # #endregion docs:project-lifecycle
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
