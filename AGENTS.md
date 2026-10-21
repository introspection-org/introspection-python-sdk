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

## Dependency check

```shell
uv sync --all-extras
uv run deptry .
```

[deptry](https://deptry.com/) fails on unused (DEP002), missing (DEP001),
transitive (DEP003) and misplaced dev (DEP004) dependencies in
`introspection_sdk/` and `scripts/`. The `Dependency Check` job in `ci.yml`
runs it on every PR. Configuration lives in `[tool.deptry]` in
`pyproject.toml`: `examples/` is its own uv project, `tests/` is not scanned,
and the `dev` / `test` extras count as dev dependencies. Import a new package
in shipped code? Declare it in `dependencies` or the extra that gates it. Do
not silence a finding with a blanket rule ignore; scope any ignore to one
package and say why next to it.

## Commits and PRs

- Keep PRs focused — one area per PR
  where possible.
- Commit messages: imperative present tense, scoped prefix
  (`feat(otel):`, `test(claude):`, `docs:`, `ci:`).
- Never commit `.env`, real API keys, or unscrubbed cassettes. The
  `gitleaks` pre-commit hook catches most of this; don't bypass it.

## Duplicate code

```shell
npx --yes jscpd@5.4.1
```

The `Duplicate Code` CI job runs the same command and fails when the
duplicated-lines share of `introspection_sdk/` exceeds `threshold` in
`.jscpd.json`. `tests/` is left out: its lower share would dilute the SDK's
and hide new copies there. The config sets `mode: "weak"`, so a copy that
differs only in comments or whitespace still counts, and lists
`kind: ["exact", "renamed"]` with `ignoreIdentifiers: true`, so a copy that
differs only in names counts too (`renamed` alone never reports identical
copies, so `exact` stays listed). The threshold is a ratchet: don't raise it
to land a change, factor the clone out instead. When a refactor lowers
duplication, read the `Total` row's duplicated-lines percentage and lower
`threshold` to just above it in the same PR. A generated file goes in the
config's `ignore` list.

## When in doubt

Read the coverage ratchet in `pyproject.toml`.
If you are an agent and the user's request conflicts with the rules above,
flag the conflict explicitly instead of silently relaxing a rule.

## Complexity ratchet

`ruff` enforces per-function complexity limits, configured in
`[tool.ruff.lint.mccabe]` and `[tool.ruff.lint.pylint]` in `pyproject.toml`:

| Rule | Setting | Threshold today | Target |
| --- | --- | --- | --- |
| `C901` complexity | `max-complexity` | 20 | 10 |
| `PLR0912` branches | `max-branches` | 20 | 12 |
| `PLR0915` statements | `max-statements` | 53 | 50 |
| `PLR0911` returns | `max-returns` | 10 | 6 |
| `PLR0917` positional args | `max-positional-args` | 5 | 5 |

The thresholds are a ratchet, like the coverage floor: each starts at
today's worst offender, and the only allowed change is down. Never raise
one to make a new function pass; split the function instead. When you
refactor an offender, lower the threshold to the new worst value in the
same PR. `PLR0913` (total arguments) is deliberately not enabled, because
the public API takes many keyword-only arguments.

All five rules run in plain `ruff check`, so the pre-commit `ruff` hook
and the `Run linting` step in CI enforce them:

```shell
uv run ruff check .
```

`PLR0917` is a preview rule, so `[tool.ruff.lint]` sets `preview = true`
together with `explicit-preview-rules = true`: preview rules run only when
selected by their exact code, so selecting `E` or `F` pulls in no preview
rules. Preview still changes some stable rules (`F822`, for one, also
checks submodules named in `__all__`); fix what they find rather than
switching preview off. `[tool.ruff.format]` keeps preview off.

## Public API compatibility

The `API Compatibility` workflow (`api-compat.yml`) runs `griffe` on every
PR and fails when the change breaks the public API of `introspection_sdk` against the
latest `v*` release tag (resolved with `git describe --tags --abbrev=0
--match 'v*' HEAD`, never hard-coded). Run the same check locally:

```shell
uv run griffe check introspection_sdk --search . --against v0.29.0
```

Pass the tag CI uses, `git describe --tags --abbrev=0 --match 'v*' HEAD`.

It needs the release tags locally (`git fetch --tags`).

What counts as public: a module's `__all__` when it has one, otherwise every
name without a leading underscore. Imported names are public only through
`__all__`. `_`-prefixed modules (`_http.py`, `_errors.py`,
`otel/_provider.py`, ...) and `_`-prefixed classes, functions and attributes
are internal and free to change. To keep a new helper out of the contract,
give it a leading underscore or leave it out of `__all__`.

Reported: a public object removed or renamed, a parameter removed, moved,
made required or changed kind, a parameter default changed, a return or
attribute type changed, a base class removed, and a changed attribute
*value*. That last one includes a pydantic `Field(description=...)` edit
or a type alias gaining a member, which are not breaking but still fail
the check. The only way through is the override below, which also bumps
the minor version; say in the PR that the break is only a value change.

### Breaking the API on purpose

1. Title the PR as a breaking Conventional Commit, e.g.
   `feat(tags)!: ...`, and describe the break and the migration under a
   `BREAKING CHANGE:` footer in the PR body. The PR title becomes the
   squash commit, so release-please bumps the minor version while we are
   below 1.0 (`bump-minor-pre-major`).
2. A maintainer who has reviewed the break adds the `api-break` label.
   Labels need triage access, so the author of an outside PR cannot apply
   it themselves.
3. Nothing to re-run: the check runs again by itself whenever the title is
   edited or a label is added or removed. It reads the label and title at
   run time, still prints every breakage, and passes with a warning. The
   label without a `!` in the title still fails, so a break cannot ship
   without a version bump, and removing either one afterwards turns the
   check red again.
