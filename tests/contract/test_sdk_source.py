"""The check over this SDK's own source, against the saved snapshots of the
references from introspection-cloud #3489 in tests/fixtures/api_contract/.

These pin what route discovery reads from the real source, not the
drift itself: the drift is the full check's to report, which runs after
each staging deploy, and fixing it must not mean editing this file.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from api_contract.check import run
from api_contract.http_calls import UNKNOWN_METHOD, requests
from api_contract.routes import discover, route_arguments, routes_of
from api_contract.source import Package, Scope

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
        # A path constant passed to a helper that posts it with httpx.
        ("POST", "/v1/oauth/token", "_async/auth.py"),
        # A helper's route plus a literal suffix, read as a stream.
        ("GET", "/v1/tasks/{}/runs/{}/stream", "resumable.py"),
    ],
)
def test_call_sites_are_found_however_the_path_is_built(
    sites, method, path, where
):
    assert where in sites[(method, path)].at


def calls(package):
    for module in package.modules.values():
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Call):
                yield module, node, Scope.of(package, module, node)


def test_every_http_call_reads_a_route(package):
    """A path built in a form route discovery cannot read would drop its
    call site without a word; only a call passing on its own caller's
    path may read none."""
    unread = []
    for module, node, scope in calls(package):
        for request in requests(node, scope):
            path = request.path
            if isinstance(path, ast.Name) and scope.is_parameter(path.id):
                continue
            if not any(r.startswith("/v1/") for r in routes_of(path, scope)):
                shown = "no path" if path is None else ast.unparse(path)
                unread.append(f"{module.line(node)}: {shown}")

    assert unread == []


def test_every_route_argument_is_sent(package):
    """A route passed to a call that discovery does not read as an HTTP
    call, a helper method or a client of a new kind, is dropped without a
    word; it fails here instead, to be read or ruled out."""
    dropped = [
        f"{module.line(node)}: {ast.unparse(node.func)}"
        for module, node, scope in calls(package)
        if route_arguments(node, scope) and not requests(node, scope)
    ]

    assert dropped == []


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
