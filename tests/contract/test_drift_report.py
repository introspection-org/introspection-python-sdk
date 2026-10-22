"""The nightly drift report and alert against a local HTTP server: staging
before it publishes the references, after it does, and when it fails."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from api_drift_report import main

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "api_contract"
NOTIFY = ROOT / "scripts" / "api_drift_notify.sh"
SKIP = "reference not published on staging yet, skipping"


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
    ):
        if body is None:
            body = (FIXTURES / f"{plane}.json").read_bytes()
        self.routes[f"/openapi/{plane}.json"] = (status, body)


@pytest.fixture
def staging() -> Iterator[Server]:
    server = Server()
    thread = threading.Thread(target=server.http.serve_forever, daemon=True)
    thread.start()
    yield server
    server.http.shutdown()


@pytest.fixture
def no_oasdiff_changes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """oasdiff reporting an empty changelog, so the SDK drift alone counts."""
    stub = tmp_path / "oasdiff"
    stub.write_text("#!/bin/sh\necho '[]'\n")
    stub.chmod(0o755)
    monkeypatch.setenv("OASDIFF", str(stub))


def report(server: Server, out: Path) -> int:
    return main(
        [
            "--out",
            str(out),
            "--controlplane",
            f"{server.url}/openapi/controlplane.json",
            "--dataplane",
            f"{server.url}/openapi/dataplane.json",
        ]
    )


def notify(report_dir: Path, state_dir: Path, webhook: str) -> str:
    done = subprocess.run(
        ["bash", str(NOTIFY)],
        env={
            "PATH": os.environ["PATH"],
            "REPORT_DIR": str(report_dir),
            "STATE_DIR": str(state_dir),
            "SLACK_WEBHOOK_URL": webhook,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


@pytest.mark.parametrize("unpublished", ["controlplane", "dataplane"])
def test_unpublished_reference_skips_and_writes_nothing(
    staging, tmp_path, capsys, unpublished
):
    for plane in ("controlplane", "dataplane"):
        if plane != unpublished:
            staging.publish(plane)
    out = tmp_path / "report"

    assert report(staging, out) == 0
    assert SKIP in capsys.readouterr().out
    assert not out.exists()


@pytest.mark.parametrize(
    ("status", "body"), [(500, b"{}"), (200, b"<html>not json")]
)
def test_other_fetch_errors_fail(staging, tmp_path, capsys, status, body):
    staging.publish("controlplane")
    staging.publish("dataplane", status, body)
    out = tmp_path / "report"

    assert report(staging, out) == 2
    printed = capsys.readouterr().out
    assert "::error::could not build the API drift report" in printed
    assert SKIP not in printed
    assert not out.exists()


def test_first_published_run_posts_its_drift_once(
    staging, tmp_path, no_oasdiff_changes
):
    """No state was recorded while staging had nothing, so the first run
    that finds the references posts: unknown to drift is a change."""
    staging.publish("controlplane")
    staging.publish("dataplane")
    out = tmp_path / "report"
    states = tmp_path / "state"
    webhook = f"{staging.url}/webhook"

    assert report(staging, out) == 0
    assert (out / "state").read_text() == "drift\n"

    assert "Posted to Slack." in notify(out, states, webhook)
    assert len(staging.posts) == 1
    text = staging.posts[0]["text"]
    assert text.startswith("🚨 API drift")
    # The message is the drift itself and the run link, nothing to paste.
    assert "controlplane: GET /v1/projects\n" in text
    assert "(local run)" in text
    assert "prompt" not in text.lower()
    assert (states / "last-posted").read_text() == "drift\n"

    assert "staying quiet" in notify(out, states, webhook)
    assert len(staging.posts) == 1
