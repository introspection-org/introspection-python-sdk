"""Route discovery on the sample SDK: which calls send a route, and every
path a call can send."""

from __future__ import annotations

from api_contract.routes import discover

from .sample import RESOURCE, line_of


def sites_at(package, line: int) -> set[tuple[str, str]]:
    return {
        (s.method, s.path)
        for s in discover(package)
        if s.at == f"sample_sdk/_async/widgets.py:{line}"
    }


def test_a_path_assigned_in_branches_keeps_every_branch(sample_package):
    resource = (
        RESOURCE
        + """

async def archive(http, widget_id, hard):
    path = WIDGETS
    if hard:
        path = _path(widget_id)
    else:
        path = f"{WIDGETS}/{widget_id}/archive"
    return await http.request("POST", path)
"""
    )

    package = sample_package(resource)

    # Both branches replace the first assignment, so it is never sent.
    assert sites_at(package, line_of('"POST", path', resource)) == {
        ("POST", "/v1/widgets/{}"),
        ("POST", "/v1/widgets/{}/archive"),
    }


def test_a_handler_sees_every_path_its_try_body_assigned(sample_package):
    resource = (
        RESOURCE
        + """

async def move(http, widget_id):
    path = WIDGETS
    try:
        path = _path(widget_id)
        await http.request("HEAD", path)
        path = f"{WIDGETS}/{widget_id}/move"
    except ValueError:
        return await http.request("GET", path)
    else:
        return await http.request("POST", path)
    finally:
        await http.request("PATCH", path)


async def rename(http, widget_id):
    try:
        path = _path(widget_id)
        path = f"{WIDGETS}/{widget_id}/rename"
    except KeyError:
        path = WIDGETS
    return await http.request("PUT", path)
"""
    )

    package = sample_package(resource)

    def sent(snippet: str) -> set[str]:
        return {p for _, p in sites_at(package, line_of(snippet, resource))}

    every = {"/v1/widgets", "/v1/widgets/{}", "/v1/widgets/{}/move"}
    assert sent('"HEAD", path') == {"/v1/widgets/{}"}
    # The body may raise before or after any of its assignments.
    assert sent('"GET", path') == every
    # The else block runs only when the whole body did.
    assert sent('"POST", path') == {"/v1/widgets/{}/move"}
    assert sent('"PATCH", path') == every
    # After the statement, only the paths of the blocks that completed.
    assert sent('"PUT", path') == {"/v1/widgets", "/v1/widgets/{}/rename"}


def test_only_http_calls_send_a_route(sample_package):
    resource = (
        RESOURCE
        + """

async def _send(http, path):
    return await http.request("PUT", path)


async def _get_widget_count(path):
    return 0


async def replace(http, logger):
    logger.warning("replacing", extra={"path": WIDGETS})
    await _get_widget_count(WIDGETS)
    return await _send(http, WIDGETS)
"""
    )

    package = sample_package(resource)

    assert sites_at(package, line_of("logger.warning", resource)) == set()
    assert sites_at(package, line_of("await _get_widget", resource)) == set()
    # A helper sends the method of the client call it passes the path to.
    assert sites_at(package, line_of("_send(http, WIDGETS)", resource)) == {
        ("PUT", "/v1/widgets")
    }
