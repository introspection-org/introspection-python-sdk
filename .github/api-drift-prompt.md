<!--
The agent prompt that ends each API drift alert in #main-build-alerts.
scripts/api_drift_report.py fills the {{...}} placeholders and drops this
comment; the rest is pasted verbatim into a coding agent, so write it as
instructions to that agent.
-->

Fix the API drift that the nightly API Contract run found in introspection-python-sdk ({{RUN_URL}}).

Where: the introspection-python-sdk repository. Fetch origin, create a new branch from origin/main, and work only there.

What: fix the SDK so that its routes match the API references, exactly for the drift listed in the SDK drift report below, and nothing else. An operation flagged for the SDK that it never calls needs a new public method, written in introspection_sdk/_async/ (then regenerate _sync/ with `uv run python scripts/gen_sync.py`), with a unit test in tests/ that follows AGENTS.md (pin the HTTP exchange with `responses`, no mocks of the HTTP client), an example and a README row. A route the SDK calls that neither reference has must be changed to the route the reference has, or deleted. The reference changelog is context: it says what changed in the staging API since the saved copies in api-reference/ were taken.

Allowed: deleting something the check reports as stale (a call to a route the references no longer have). List each one you delete in the PR body.

Never:

- add an exemption, allowlist or skip of any kind to scripts/api_contract/ or scripts/check_api_contract.py;
- edit the reference URLs (DEFAULT_URLS in scripts/api_contract/reference.py);
- weaken, skip or delete a test to make it pass.

Questions, not changes: put these in the PR body as questions and leave the code alone.

- An SDK API break: a fix that would remove or retype something callers of the SDK use today. Ask whether to break it now or deprecate it first.
- A reference that looks wrong rather than the SDK (an operation flagged for the SDK that no SDK user needs, say). Ask whether to fix the cloud's API surface instead.

Finish: when the drift is fixed, refresh both saved copies from staging:

curl -fsS https://api.staging.introspection.dev/openapi/controlplane.json -o api-reference/controlplane.json
curl -fsS https://api.staging.introspection.dev/openapi/dataplane.json -o api-reference/dataplane.json

Stop when the check passes: `uv run python scripts/check_api_contract.py` exits 0, and `uv run pytest tests/`, `uv run ruff check .` and `uv run ty check` pass.

Output: one pull request against main, with conventional commit messages. Its body lists the drift fixed, the stale items deleted and the questions above.

If a report below ends with a trim marker, run `uv run python scripts/check_api_contract.py`, or `oasdiff changelog` against the saved copy, for the full list.

SDK drift (uv run python scripts/check_api_contract.py):

{{SDK_DRIFT}}

Reference changelog (oasdiff, api-reference/ saved copy vs staging):

{{CHANGELOG}}
