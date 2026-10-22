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


def test_a_loop_carries_its_body_into_later_passes_and_else(sample_package):
    resource = (
        RESOURCE
        + """

async def sweep(http, ids):
    path = WIDGETS
    for widget_id in ids:
        await http.request("HEAD", path)
        if not widget_id:
            continue
        path = _path(widget_id)
        if widget_id == "stop":
            path = f"{WIDGETS}/{widget_id}/stop"
            break
        path = f"{WIDGETS}/{widget_id}/swept"
    else:
        await http.request("GET", path)
    return await http.request("POST", path)


async def drain(http, ids):
    path = WIDGETS
    while ids:
        path = _path(ids.pop())
    else:
        await http.request("DELETE", path)
"""
    )

    package = sample_package(resource)

    def sent(snippet: str) -> set[str]:
        return {p for _, p in sites_at(package, line_of(snippet, resource))}

    # A pass starts where the loop or an earlier pass or `continue` left.
    assert sent('"HEAD", path') == {"/v1/widgets", "/v1/widgets/{}/swept"}
    # `else` follows zero or more completed passes, never a `break`.
    assert sent('"GET", path') == {"/v1/widgets", "/v1/widgets/{}/swept"}
    assert sent('"POST", path') == {
        "/v1/widgets",
        "/v1/widgets/{}/swept",
        "/v1/widgets/{}/stop",
    }
    assert sent('"DELETE", path') == {"/v1/widgets", "/v1/widgets/{}"}


def test_a_match_keeps_each_case(sample_package):
    resource = (
        RESOURCE
        + """

async def act(http, action, widget_id):
    path = WIDGETS
    match action:
        case "get":
            path = _path(widget_id)
            await http.request("GET", path)
        case "archive" if widget_id:
            path = f"{WIDGETS}/{widget_id}/archive"
    return await http.request("POST", path)


async def act_or_list(http, action, widget_id):
    match action:
        case "get":
            path = _path(widget_id)
        case _:
            path = WIDGETS
    return await http.request("PUT", path)
"""
    )

    package = sample_package(resource)

    def sent(snippet: str) -> set[str]:
        return {p for _, p in sites_at(package, line_of(snippet, resource))}

    assert sent('"GET", path') == {"/v1/widgets/{}"}
    # No case matched keeps the path from before the match.
    assert sent('"POST", path') == {
        "/v1/widgets",
        "/v1/widgets/{}",
        "/v1/widgets/{}/archive",
    }
    # A catch-all case leaves no path through.
    assert sent('"PUT", path') == {"/v1/widgets", "/v1/widgets/{}"}


def test_with_blocks_and_except_star_run_in_sequence(sample_package):
    resource = (
        RESOURCE
        + """

async def lock(http, lock, widget_id):
    path = WIDGETS
    async with lock:
        with lock:
            path = _path(widget_id)
            await http.request("GET", path)
    try:
        path = f"{WIDGETS}/{widget_id}/lock"
    except* ValueError:
        await http.request("DELETE", path)
    return await http.request("POST", path)
"""
    )

    package = sample_package(resource)

    def sent(snippet: str) -> set[str]:
        return {p for _, p in sites_at(package, line_of(snippet, resource))}

    assert sent('"GET", path') == {"/v1/widgets/{}"}
    assert sent('"DELETE", path') == {"/v1/widgets/{}", "/v1/widgets/{}/lock"}
    # The handler falls through with what the body had assigned.
    assert sent('"POST", path') == {"/v1/widgets/{}", "/v1/widgets/{}/lock"}
