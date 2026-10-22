"""The check over this SDK's own source, against the saved snapshots of the
references from introspection-cloud #3489 in tests/fixtures/api_contract/.

These pin what route discovery reads from the real source, not the
drift itself: the drift is the nightly workflow's to report, and fixing it
must not mean editing this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_contract.check import run
from api_contract.routes import UNKNOWN_METHOD, discover
from api_contract.source import Package

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "api_contract"


@pytest.fixture(scope="module")
def package() -> Package:
    return Package.load(ROOT)


@pytest.fixture(scope="module")
def sites(package):
    return {(s.method, s.path): s for s in discover(package)}


def test_generated_sync_twins_are_not_read(package):
    assert not any("_sync" in name.split(".") for name in package.modules)


@pytest.mark.parametrize(
    ("method", "path", "where"),
    [
        # A literal path.
        ("GET", "/v1/tasks", "runner_resources/tasks.py"),
        # A module constant in an f-string, through a path helper.
        ("DELETE", "/v1/connections/{}", "runner_resources/connections.py"),
        # A helper that returns one of two routes.
        (
            "GET",
            "/v1/repositories/{}/contents/{}",
            "resources/repositories.py",
        ),
        ("GET", "/v1/repositories/{}/contents", "resources/repositories.py"),
        # A path constant passed to a helper whose name says POST.
        ("POST", "/v1/oauth/token", "_async/auth.py"),
        # A helper's route plus a literal suffix, read as a stream.
        ("GET", "/v1/tasks/{}/runs/{}/stream", "resumable.py"),
    ],
)
def test_call_sites_are_found_however_the_path_is_built(
    sites, method, path, where
):
    assert where in sites[(method, path)].at


def test_every_call_site_has_a_method(package):
    assert not any(s.method == UNKNOWN_METHOD for s in discover(package))


def test_check_against_the_3489_snapshots_reads_every_route(package):
    specs = {
        plane: json.loads((FIXTURES / f"{plane}.json").read_text())
        for plane in ("controlplane", "dataplane")
    }

    result = run(package, specs)

    assert result.operations == 85 + 79
    assert result.unknown_route == []
