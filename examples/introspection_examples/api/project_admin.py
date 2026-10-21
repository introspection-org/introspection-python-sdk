"""Administer a project: who you are, its API keys and runtime settings.

Reads the signed-in member, the org's projects, and a project's API keys,
credentials, variables and judges; then, when INTROSPECTION_ADMIN_WRITE=1,
mints an API key, saves its one-time plaintext, acknowledges it and revokes
it again.

These routes need an org credential: an owner's or admin's Control Plane
session (or an access token minted for one). A project API key carries none
of their scopes and gets a 403, which is why this example is not in
``examples.yml``.

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
        sys.exit(
            "Set INTROSPECTION_CP_SESSION to an owner's Control Plane session "
            "and INTROSPECTION_PROJECT to a project slug or id."
        )

    client = IntrospectionClient(cp_session=session)
    try:
        # #region docs:project-admin
        me = client.oidc.me()
        print(f"signed in as member {me.member_id} of org {me.org_id}")

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
        # #endregion docs:project-admin

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
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
