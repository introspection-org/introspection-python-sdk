"""The contract check script against a local staging server: before it
publishes the references, on a pull request, and after a staging deploy,
when it tells Slack about each change of state."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from check_api_contract import SKIP, main, slack_escape, trim

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "api_contract"
#: A route the SDK calls, flagged for it in the dataplane fixture.
CALLED = "/v1/conversations/{conversation_id}/items"


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
        self.routes[f"/openapi/{plane}.json"] = (status, body)

    def publish_both(self) -> None:
        self.publish("controlplane")
        self.publish("dataplane")


@pytest.fixture
def staging(monkeypatch: pytest.MonkeyPatch) -> Iterator[Server]:
    server = Server()
    thread = threading.Thread(target=server.http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("SLACK_WEBHOOK_URL", f"{server.url}/webhook")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    yield server
    server.http.shutdown()


def publish_unflagged(server: Server) -> None:
    """Both references with no operation flagged for any client."""
    for plane in ("controlplane", "dataplane"):
        spec = json.loads((FIXTURES / f"{plane}.json").read_text())
        for item in spec["paths"].values():
            for op in item.values():
                if isinstance(op, dict):
                    op.pop("x-introspection", None)
        server.publish(plane, body=json.dumps(spec).encode())


def check(server: Server, *flags: str) -> int:
    return main(
        [
            "--controlplane",
            f"{server.url}/openapi/controlplane.json",
            "--dataplane",
            f"{server.url}/openapi/dataplane.json",
            *flags,
        ]
    )


@pytest.mark.parametrize("unpublished", ["controlplane", "dataplane"])
@pytest.mark.parametrize("pr", [True, False])
def test_unpublished_reference_skips_green(
    staging, tmp_path, capsys, unpublished, pr
):
    states = tmp_path / "state"
    flags = ["--pr"] if pr else ["--notify", str(states)]
    for plane in ("controlplane", "dataplane"):
        if plane != unpublished:
            staging.publish(plane)

    assert check(staging, *flags) == 0
    assert SKIP in capsys.readouterr().out
    assert staging.posts == []
    assert not states.exists()


@pytest.mark.parametrize(
    ("status", "body"), [(500, b"{}"), (200, b"<html>not json")]
)
def test_other_fetch_errors_fail(staging, capsys, status, body):
    staging.publish("controlplane")
    staging.publish("dataplane", status, body)

    assert check(staging, "--pr") == 2
    printed = capsys.readouterr().out
    assert "::error::could not run the API contract check" in printed
    assert SKIP not in printed


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
    """No state is recorded while staging has nothing, so the first run
    that finds the references posts: unknown to drift is a change."""
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
    assert output.read_text() == "posted=true\n"

    assert check(staging, "--notify", str(states)) == 1
    assert len(staging.posts) == 1
    assert output.read_text().endswith("posted=false\n")

    # The cloud drops every flag for the SDK: the drift clears.
    publish_unflagged(staging)

    assert check(staging, "--notify", str(states)) == 0
    assert staging.posts[1]["text"].startswith("✅ API drift cleared")
    assert (states / "last-posted").read_text() == "clean\n"


def test_clean_without_a_posted_drift_stays_quiet(staging, tmp_path, capsys):
    publish_unflagged(staging)

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
