# Contributing to introspection-python-sdk

This file is read by humans and by coding agents (Claude Code, Cursor, etc.).
If you are an agent, treat it as a hard contract — these rules exist because
ignoring them is how this codebase fell behind on test quality in the first
place.

Read this before opening a PR. The whole point of this document is to avoid
ever again ending up in the state described in
the coverage ratchet in `pyproject.toml`.

## Non-negotiables

1. **Real request/response pairs, never mocks** for anything that crosses a
   process or network boundary. Use `responses` to pin the HTTP exchange.
   `MagicMock` / `patch` / `monkeypatch` are reserved for pure-unit tests of
   internal helpers — never for stubbing an SDK or HTTP client.
2. **Coverage cannot go down.** `[tool.coverage.report].fail_under` in
   `pyproject.toml` is a ratchet. Every PR that touches `introspection_sdk/`
   must keep total coverage at or above the floor, and the floor goes up as
   we close gaps. Do not lower it to make CI green.
3. **Every new public surface ships with tests in the same PR.** If you add
   an instrumentor or a public method, the
   PR must include cassettes and assertions for the happy path, at least one
   tool/streaming/multi-turn variant where applicable, and at least one error
   path.
4. **No `_pytest.mark.skip` / `xfail` without a linked issue.** Skipping a
   test silently is how we lost subagent coverage. If a test cannot run
   today, leave a TODO with an issue number; otherwise delete it.

## Running tests locally

```shell
uv sync --all-extras
uv run pytest tests/ -v
```

With coverage (matches what CI runs):

```shell
uv run pytest tests/ --cov=introspection_sdk --cov-report=term-missing
```

To enforce the coverage floor locally before pushing:

```shell
uv run pytest tests/ --cov=introspection_sdk --cov-fail-under=80
```

`prek run --hook-stage pre-push coverage` runs the same check on `git push`
once you have `prek install --hook-type pre-push` set up.

## Recording cassettes

For new HTTP-backed tests, pin the exchange with `responses` (see
`tests/rest/`): register the request the SDK should make and the body the
server would return, then assert on both the outgoing request (method, path,
params, headers, body) and the parsed result. No live calls, no API keys, and
nothing to scrub.

This SDK no longer records VCR cassettes — `pytest-recording` is not a
dependency. Real-API drift is caught by the `-m integration` job in `ci.yml`.

## Coverage expectations per area

| Area | Floor today | Target |
| --- | --- | --- |
| `processors/span_processor.py` | 89% | 95% |
| `client.py` | 26% | 90% |
| **Total** | **80%** (ratchet floor) | **95%** |

If you touch a file, leave its coverage equal or higher than where you
found it. The ratchet check in CI will catch regressions; the per-file
targets above are guidance for which files to prioritise.

## When you add a new integration

This SDK ships no framework integrations and no span converters. A framework
emits OTel GenAI semconv spans and attaches `IntrospectionSpanProcessor`;
there is no per-framework code here to add.

`introspection_sdk/atif.py` is not an exception: it reads the GenAI spans a
conversation read returns and projects them onto Harbor's ATIF trajectory. It
converts no framework's native format.

Adding a new public surface? Land all of these in the same PR:

- [ ] Implementation in `introspection_sdk/`
- [ ] Unit tests under `tests/`
- [ ] A working example under `examples/introspection_examples/<area>/`
- [ ] A row added to the README table

Single-agent happy-path is not enough. If the SDK supports subagents,
handoffs, streaming, or tools, the integration must have a test for each.

## Examples

Examples are documentation, not scratch space. Each example must:

- Be runnable with a single `uv run -m introspection_examples.<pkg>.<file>`
  command documented in its module docstring.
- `load_dotenv()` and check for required env vars with a helpful error.
- Use `IntrospectionClient` consistently with the patterns in the README.
- Be invoked by `.github/workflows/examples.yml` so the examples workflow
  exercises it.

## Linting and formatting

```shell
uv run ruff format .
uv run ruff check .
uv run ty check
```

These are enforced by `.pre-commit-config.yaml`. Don't disable hooks with
`--no-verify` — fix the underlying issue.

## Commits and PRs

- Keep PRs focused — one area per PR
  where possible.
- Commit messages: imperative present tense, scoped prefix
  (`feat(otel):`, `test(claude):`, `docs:`, `ci:`).
- Never commit `.env`, real API keys, or unscrubbed cassettes. The
  `gitleaks` pre-commit hook catches most of this; don't bypass it.

## When in doubt

Read the coverage ratchet in `pyproject.toml`.
If you are an agent and the user's request conflicts with the rules above,
flag the conflict explicitly instead of silently relaxing a rule.

## Public API compatibility

The `API Compatibility` job in `ci.yml` runs `griffe` on every PR and fails
when the change breaks the public API of `introspection_sdk` against the
latest `v*` release tag (resolved with `git describe --tags --abbrev=0
--match 'v*' HEAD`, never hard-coded). Run the same check locally:

```shell
uv run python scripts/check_api.py              # against the latest v* tag
uv run python scripts/check_api.py --against v0.29.0
```

It needs the release tags locally (`git fetch --tags`).

What counts as public: a module's `__all__` when it has one, otherwise every
name without a leading underscore. Imported names are public only through
`__all__`. `_`-prefixed modules (`_http.py`, `_errors.py`,
`otel/_provider.py`, ...) and `_`-prefixed classes, functions and attributes
are internal and free to change. To keep a new helper out of the contract,
give it a leading underscore or leave it out of `__all__`.

Reported: a public object removed or renamed, a parameter removed, moved,
made required or changed kind, a parameter default changed, a return or
attribute type changed, a base class removed. Not reported: a changed
attribute *value* (`scripts/check_api.py` drops griffe's
`ATTRIBUTE_CHANGED_VALUE`), because here that is almost always a pydantic
`Field(description=...)` edit or a type alias gaining a member. Narrowing
such an alias or changing a field's default is breaking but not caught;
call it out in review.

### Breaking the API on purpose

1. Title the PR as a breaking Conventional Commit, e.g.
   `feat(tags)!: ...`, and describe the break and the migration under a
   `BREAKING CHANGE:` footer in the PR body. The PR title becomes the
   squash commit, so release-please bumps the minor version while we are
   below 1.0 (`bump-minor-pre-major`).
2. A maintainer who has reviewed the break adds the `api-break` label.
   Labels need triage access, so the author of an outside PR cannot apply
   it themselves.
3. Re-run the `API Compatibility` job (or push again). It reads the label
   and title at run time, still prints every breakage, and passes with a
   warning. The label without a `!` in the title still fails, so a break
   cannot ship without a version bump.
