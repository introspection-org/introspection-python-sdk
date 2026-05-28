# Contributing to introspection-python-sdk

This file is read by humans and by coding agents (Claude Code, Cursor, etc.).
If you are an agent, treat it as a hard contract — these rules exist because
ignoring them is how this codebase fell behind on test quality in the first
place.

Read this before opening a PR. The whole point of this document is to avoid
ever again ending up in the state described in
[`docs/test-quality-audit-plan.md`](docs/test-quality-audit-plan.md).

## Non-negotiables

1. **Recordings, never mocks** for anything that crosses a process or network
   boundary. Use `pytest-recording` (VCR cassettes) for HTTP, and the
   recording transport in `introspection_sdk/testing/` for the Claude Agent
   SDK subprocess. `MagicMock` / `patch` / `monkeypatch` are reserved for
   pure-unit tests of internal helpers — never for stubbing an SDK or HTTP
   client.
2. **Coverage cannot go down.** `[tool.coverage.report].fail_under` in
   `pyproject.toml` is a ratchet. Every PR that touches `introspection_sdk/`
   must keep total coverage at or above the floor, and the floor goes up as
   we close gaps. Do not lower it to make CI green.
3. **Every new public surface ships with tests in the same PR.** If you add
   an instrumentor, a converter, a callback handler, or a public method, the
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
uv run pytest tests/ --cov=introspection_sdk --cov-fail-under=60
```

`prek run --hook-stage pre-push coverage` runs the same check on `git push`
once you have `prek install --hook-type pre-push` set up.

## Recording cassettes

For new HTTP-backed tests:

1. Add the test with `@pytest.mark.vcr()`.
2. Make sure the appropriate API key is set in your environment
   (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, …).
3. Run once with `--record-mode=once`:

   ```shell
   uv run pytest tests/path/to/new_test.py --record-mode=once
   ```

4. Inspect the generated cassette under `tests/<area>/cassettes/<test_file>/`
   and confirm:
   - No real API keys, bearer tokens, or session IDs leaked through. The
     scrubbers in `tests/conftest.py` cover the common patterns; if you add
     a new provider, extend `SENSITIVE_HEADERS` and `_SECRET_PATTERNS`.
   - The interaction is minimal — trim unused turns rather than recording
     huge transcripts.
5. Commit the cassette alongside the test.

For Claude Agent SDK tests, use the recording transport (see
`docs/test-quality-audit-plan.md` Phase 2). Do **not** add new tests that
mock `claude_agent_sdk` at the module level — extend the transport instead.

## Coverage expectations per area

| Area | Floor today | Target |
| --- | --- | --- |
| `processors/span_processor.py` | 89% | 95% |
| `processors/tracing_processor.py` | 84% | 95% |
| `processors/claude_tracing_processor.py` | 74% | 95% |
| `processors/langchain_callback_handler.py` | 15% | 90% |
| `converters/openinference.py` | 62% | 90% |
| `converters/genai_to_openinference.py` | 25% | 90% |
| `anthropic.py` / `gemini.py` | ~73% | 95% |
| `client.py` | 26% | 90% |
| **Total** | **60%** (ratchet floor) | **95%** |

If you touch a file, leave its coverage equal or higher than where you
found it. The ratchet check in CI will catch regressions; the per-file
targets above are guidance for which files to prioritise.

## When you add a new integration

Adding a new framework or observability backend? Land all of these in the
same PR:

- [ ] Implementation in `introspection_sdk/`
- [ ] Unit/recording tests under `tests/framework/` (for instrumented
      frameworks) or `tests/observability/` (for observability backends)
- [ ] At least one dual-export integration test where applicable
- [ ] A working example under `examples/introspection_examples/<area>/`
- [ ] A row added to the README integration table
- [ ] A row added to the "framework × observability" matrix in
      `docs/test-quality-audit-plan.md` — turn the relevant cell green

Single-agent happy-path is not enough. If the SDK supports subagents,
handoffs, streaming, or tools, the integration must have a test for each.

## Examples

Examples are documentation, not scratch space. Each example must:

- Be runnable with a single `uv run -m introspection_examples.<pkg>.<file>`
  command documented in its module docstring.
- `load_dotenv()` and check for required env vars with a helpful error.
- Use `IntrospectionClient` consistently with the patterns in the README.
- Be added to `examples/run_all.sh` so the nightly examples workflow
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

- Keep PRs focused — one phase of `docs/test-quality-audit-plan.md` per PR
  where possible.
- Commit messages: imperative present tense, scoped prefix
  (`feat(gemini):`, `test(claude):`, `docs:`, `ci:`).
- Never commit `.env`, real API keys, or unscrubbed cassettes. The
  `gitleaks` pre-commit hook catches most of this; don't bypass it.

## When in doubt

Read [`docs/test-quality-audit-plan.md`](docs/test-quality-audit-plan.md).
If you are an agent and the user's request conflicts with the rules above,
flag the conflict explicitly instead of silently relaxing a rule.
