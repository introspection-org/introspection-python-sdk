"""The contract check script against a local staging server: on a pull
request, after a staging deploy, when it tells Slack about each change of
state, and when a reference cannot be read."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from check_api_contract import main, slack_escape, trim

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "api_contract"
#: A route the SDK calls, flagged for it in the dataplane fixture.
CALLED = "/v1/conversations/{conversation_id}/items"
#: Where the local staging server serves each plane, as staging does: each
#: plane's own `/openapi.json`.
PREFIXES = {"controlplane": "/cp", "dataplane": "/dp"}
ERROR = "::error::could not run the API contract check"


class Server:
    """Answers each path with a pinned status and body; records POSTs."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.posts: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, body = server.routes.get(self.path, (404, b"{}"))
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                server.posts.append(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_port}"

    def publish(
        self, plane: str, status: int = 200, body: bytes | None = None
    ) -> None:
        if body is None:
            body = (FIXTURES / f"{plane}.json").read_bytes()
        self.routes[f"{PREFIXES[plane]}/openapi.json"] = (status, body)

    def publish_both(self) -> None:
        self.publish("controlplane")
        self.publish("dataplane")


@pytest.fixture
def staging(monkeypatch: pytest.MonkeyPatch) -> Iterator[Server]:
    server = Server()
    thread = threading.Thread(target=server.http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("SLACK_WEBHOOK_URL", f"{server.url}/webhook")
    # Both planes are read through their base URLs, as the workflow does.
    monkeypatch.setenv("INTROSPECTION_CP_URL", f"{server.url}/cp")
    monkeypatch.setenv("INTROSPECTION_DP_URL", f"{server.url}/dp/")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    yield server
    server.http.shutdown()


def publish_for_no_client(server: Server) -> None:
    """Both references with every operation flagged for no client."""
    for plane in ("controlplane", "dataplane"):
        spec = json.loads((FIXTURES / f"{plane}.json").read_text())
        for item in spec["paths"].values():
            for op in item.values():
                if isinstance(op, dict):
                    op["x-introspection"] = {"clients": []}
        server.publish(plane, body=json.dumps(spec).encode())


def check(server: Server, *flags: str) -> int:
    return main(list(flags))


def record(states: Path, state: str) -> None:
    states.mkdir()
    (states / "last-posted").write_text(f"{state}\n")


@pytest.mark.parametrize(
    "failure",
    [
        (plane, status, body)
        for plane in ("controlplane", "dataplane")
        for status, body in (
            (404, b"{}"),
            (500, b"{}"),
            (200, b"<html>not json"),
        )
    ],
)
def test_a_failed_fetch_fails_without_posting_or_changing_state(
    staging, tmp_path, monkeypatch, capsys, failure
):
    """A 404 is a failure like any other: no skip, no post, and the posted
    drift stays recorded, so a failed read never reads as cleared."""
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    states = tmp_path / "state"
    record(states, "drift")
    staging.publish_both()
    staging.publish(*failure)

    assert check(staging, "--notify", str(states)) == 2
    assert ERROR in capsys.readouterr().out
    assert staging.posts == []
    assert (states / "last-posted").read_text() == "drift\n"
    assert not output.exists()


def test_an_unreachable_reference_fails_without_posting(
    staging, tmp_path, monkeypatch, capsys
):
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    states = tmp_path / "state"
    record(states, "clean")
    staging.publish_both()
    # Nothing listens on port 9 of localhost: the connection is refused.
    monkeypatch.setenv("INTROSPECTION_DP_URL", "http://127.0.0.1:9")

    assert check(staging, "--notify", str(states)) == 2
    assert ERROR in capsys.readouterr().out
    assert staging.posts == []
    assert (states / "last-posted").read_text() == "clean\n"
    assert not output.exists()


def test_drift_still_marks_both_references_read(
    staging, tmp_path, monkeypatch
):
    """The workflow records a dispatch's base URLs only on references=read:
    drift (a red run) read both documents, so its pair is recorded, while
    a failed fetch above writes no output and its pair is not."""
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    states = tmp_path / "state"
    record(states, "drift")
    staging.publish_both()

    assert check(staging, "--notify", str(states)) == 1
    assert output.read_text().splitlines() == [
        "references=read",
        "posted=false",
    ]


def test_the_workflow_saves_the_urls_only_once_both_references_were_read():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "api-contract.yml").read_text()
    )
    steps = {
        step.get("name"): step
        for step in workflow["jobs"]["api-contract"]["steps"]
    }
    save = steps["Save the reference URLs"]
    assert save["with"]["path"] == ".api-reference-urls"
    assert "steps.urls.outputs.source == 'payload'" in save["if"]
    assert "steps.check.outputs.references == 'read'" in save["if"]
    ids = [step.get("id") for step in steps.values()]
    assert "check" in ids


@pytest.mark.parametrize(
    "case",
    [
        (pr, var, value)
        for pr in (True, False)
        for var in ("INTROSPECTION_CP_URL", "INTROSPECTION_DP_URL")
        for value in (None, "")
    ],
)
def test_an_unset_base_url_fails_naming_the_variable(
    staging, tmp_path, monkeypatch, capsys, case
):
    pr, var, value = case
    if value is None:
        monkeypatch.delenv(var)
    else:
        monkeypatch.setenv(var, value)
    states = tmp_path / "state"
    record(states, "drift")
    staging.publish_both()
    flags = ["--pr"] if pr else ["--notify", str(states)]

    assert check(staging, *flags) == 2
    printed = capsys.readouterr().out
    assert ERROR in printed
    assert f"{var} is unset or empty" in printed
    assert staging.posts == []
    assert (states / "last-posted").read_text() == "drift\n"


def test_pr_reports_uncalled_operations_without_failing(
    staging, tmp_path, monkeypatch, capsys
):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    staging.publish_both()

    assert check(staging, "--pr") == 0
    assert "reported only, never fails a PR" in capsys.readouterr().out
    assert "controlplane: GET /v1/projects\n" in summary.read_text()
    assert staging.posts == []


def test_flags_name_the_documents_instead_of_the_base_urls(
    staging, tmp_path, monkeypatch
):
    monkeypatch.delenv("INTROSPECTION_CP_URL")
    monkeypatch.delenv("INTROSPECTION_DP_URL")
    staging.publish("controlplane")

    assert (
        check(
            staging,
            "--pr",
            "--controlplane",
            f"{staging.url}/cp/openapi.json",
            "--dataplane",
            str(FIXTURES / "dataplane.json"),
        )
        == 0
    )


def test_pr_fails_on_a_route_in_neither_reference(staging, capsys):
    dataplane = json.loads((FIXTURES / "dataplane.json").read_text())
    del dataplane["paths"][CALLED]
    staging.publish("controlplane")
    staging.publish("dataplane", body=json.dumps(dataplane).encode())

    assert check(staging, "--pr") == 1
    assert "GET /v1/conversations/{}/items (" in capsys.readouterr().out


def test_full_check_posts_each_change_of_state_once(
    staging, tmp_path, monkeypatch
):
    """With no state recorded yet, the first run posts: unknown to drift is
    a change."""
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    states = tmp_path / "state"
    staging.publish_both()

    assert check(staging, "--notify", str(states)) == 1
    assert len(staging.posts) == 1
    text = staging.posts[0]["text"]
    assert text.startswith("🚨 API drift")
    # The message is the drift itself and the run link, nothing to paste.
    assert "controlplane: GET /v1/projects\n" in text
    assert "(local run)" in text
    assert "prompt" not in text.lower()
    assert (states / "last-posted").read_text() == "drift\n"
    assert output.read_text() == "references=read\nposted=true\n"

    assert check(staging, "--notify", str(states)) == 1
    assert len(staging.posts) == 1
    assert output.read_text().endswith("posted=false\n")

    # The cloud flags every operation for no client: the drift clears.
    publish_for_no_client(staging)

    assert check(staging, "--notify", str(states)) == 0
    assert staging.posts[1]["text"].startswith("✅ API drift cleared")
    assert (states / "last-posted").read_text() == "clean\n"


def test_clean_without_a_posted_drift_stays_quiet(staging, tmp_path, capsys):
    publish_for_no_client(staging)

    assert check(staging, "--notify", str(tmp_path / "state")) == 0
    assert "staying quiet" in capsys.readouterr().out
    assert staging.posts == []


def test_empty_webhook_prints_instead_of_posting(
    staging, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "")
    staging.publish_both()

    assert check(staging, "--notify", str(tmp_path / "state")) == 1
    out = capsys.readouterr().out
    assert "Slack post withheld (no webhook)" in out
    assert "🚨 API drift" in out
    assert staging.posts == []
    # A withheld post records no state, so the real one still fires.
    assert not (tmp_path / "state").exists()


def test_trim_keeps_whole_lines_and_says_how_many_are_left():
    text = "\n".join(f"line {i}" for i in range(10))

    assert trim(text, 1000) == text
    assert (
        trim(text, 14) == "line 0\nline 1\n… 8 more lines, in the job summary"
    )


def test_slack_control_characters_are_escaped():
    assert slack_escape("a < b & c > d") == "a &lt; b &amp; c &gt; d"
