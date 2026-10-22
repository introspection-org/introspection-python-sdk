"""The nightly drift alert: the report's text and the notify decision."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from api_contract.changelog import render_plane
from api_drift_report import prompt, slack_escape, trim

ROOT = Path(__file__).resolve().parents[2]
NOTIFY = ROOT / "scripts" / "api_drift_notify.sh"


def test_trim_keeps_whole_lines_and_says_how_many_are_left():
    text = "\n".join(f"line {i}" for i in range(10))

    assert trim(text, 1000) == text
    assert (
        trim(text, 14) == "line 0\nline 1\n… 8 more lines, in the job summary"
    )


def test_slack_control_characters_are_escaped():
    assert slack_escape("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_prompt_fills_every_placeholder_and_drops_the_comment():
    text = prompt("https://run", "drift here", ["cp changes", "dp changes"])

    assert "{{" not in text
    assert "<!--" not in text
    assert text.startswith("Fix the API drift")
    assert "https://run" in text
    assert "drift here" in text
    assert "cp changes\n\ndp changes" in text
    assert "never" in text.lower()


def test_changelog_groups_one_change_across_operations():
    changes = [
        {
            "id": "endpoint-added",
            "operation": "GET",
            "path": "/v1/new",
            "level": 1,
        },
        {
            "id": "new-required-request-parameter",
            "operation": "GET",
            "path": "/v1/a",
            "level": 3,
            "text": "added the new required `query` request parameter `x`",
        },
        {
            "id": "new-required-request-parameter",
            "operation": "GET",
            "path": "/v1/b",
            "level": 3,
            "text": "added the new required `query` request parameter `x`",
        },
    ]

    got = render_plane("dataplane", changes)

    assert got.changed
    assert got.header.startswith("dataplane: 3 changes — 2 breaking")
    assert "operations added: GET /v1/new" in got.text
    assert (
        "BREAKING: added the new required `query` request parameter `x` "
        "— GET /v1/a, GET /v1/b"
    ) in got.text
    assert not render_plane("dataplane", []).changed


def notify(tmp_path: Path, state: str, last: str | None) -> tuple[str, Path]:
    report = tmp_path / "report"
    report.mkdir(exist_ok=True)
    (report / "state").write_text(f"{state}\n")
    (report / "body.txt").write_text("the body\n")
    states = tmp_path / "state"
    if last is not None:
        states.mkdir(exist_ok=True)
        (states / "last-posted").write_text(f"{last}\n")
    output = tmp_path / "output"
    env = {
        "PATH": os.environ["PATH"],
        "REPORT_DIR": str(report),
        "STATE_DIR": str(states),
        "SLACK_WEBHOOK_URL": "",
        "GITHUB_OUTPUT": str(output),
    }
    done = subprocess.run(
        ["bash", str(NOTIFY)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout, output


def test_new_drift_prints_the_alert_when_the_webhook_is_empty(tmp_path):
    out, output = notify(tmp_path, "drift", None)

    assert "Slack post withheld (no webhook)" in out
    assert "🚨 API drift" in out
    assert "the body" in out
    assert output.read_text() == "posted=false\n"
    # A rehearsal never records a post, so the real one still fires.
    assert not (tmp_path / "state" / "last-posted").exists()


def test_cleared_drift_is_an_edge(tmp_path):
    out, _ = notify(tmp_path, "clean", "drift")

    assert "✅ API drift cleared" in out


def test_drift_that_stays_drift_is_quiet(tmp_path):
    out, output = notify(tmp_path, "drift", "drift")

    assert "staying quiet" in out
    assert "Slack post withheld" not in out
    assert output.read_text() == "posted=false\n"


def test_clean_that_stays_clean_is_quiet(tmp_path):
    out, _ = notify(tmp_path, "clean", None)

    assert "staying quiet" in out
    assert "Rehearsal" not in out
