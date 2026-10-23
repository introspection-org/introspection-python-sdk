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


def sent(package, resource: str, snippet: str) -> set[str]:
    """The paths the call on the line of `snippet` sends."""
    return {p for _, p in sites_at(package, line_of(snippet, resource))}


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

    every = {"/v1/widgets", "/v1/widgets/{}", "/v1/widgets/{}/move"}
    assert sent(package, resource, '"HEAD", path') == {"/v1/widgets/{}"}
    # The body may raise before or after any of its assignments.
    assert sent(package, resource, '"GET", path') == every
    # The else block runs only when the whole body did.
    assert sent(package, resource, '"POST", path') == {"/v1/widgets/{}/move"}
    assert sent(package, resource, '"PATCH", path') == every
    # After the statement, only the paths of the blocks that completed.
    assert sent(package, resource, '"PUT", path') == {
        "/v1/widgets",
        "/v1/widgets/{}/rename",
    }


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

    # A pass starts where the loop or an earlier pass or `continue` left.
    assert sent(package, resource, '"HEAD", path') == {
        "/v1/widgets",
        "/v1/widgets/{}/swept",
    }
    # `else` follows zero or more completed passes, never a `break`.
    assert sent(package, resource, '"GET", path') == {
        "/v1/widgets",
        "/v1/widgets/{}/swept",
    }
    assert sent(package, resource, '"POST", path') == {
        "/v1/widgets",
        "/v1/widgets/{}/swept",
        "/v1/widgets/{}/stop",
    }
    assert sent(package, resource, '"DELETE", path') == {
        "/v1/widgets",
        "/v1/widgets/{}",
    }


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

    assert sent(package, resource, '"GET", path') == {"/v1/widgets/{}"}
    # No case matched keeps the path from before the match.
    assert sent(package, resource, '"POST", path') == {
        "/v1/widgets",
        "/v1/widgets/{}",
        "/v1/widgets/{}/archive",
    }
    # A catch-all case leaves no path through.
    assert sent(package, resource, '"PUT", path') == {
        "/v1/widgets",
        "/v1/widgets/{}",
    }


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

    assert sent(package, resource, '"GET", path') == {"/v1/widgets/{}"}
    assert sent(package, resource, '"DELETE", path') == {
        "/v1/widgets/{}",
        "/v1/widgets/{}/lock",
    }
    # The handler falls through with what the body had assigned.
    assert sent(package, resource, '"POST", path') == {
        "/v1/widgets/{}",
        "/v1/widgets/{}/lock",
    }


def test_a_call_sends_by_what_its_receiver_is(sample_package):
    resource = (
        RESOURCE
        + """

import httpx

HEALTH = "/v1/health"


async def look(cache, headers, client):
    cache.delete(WIDGETS)
    headers.get(HEALTH)
    await client.post(WIDGETS)


async def watch(base):
    async with httpx.AsyncClient(base_url=base) as client:
        async with client.stream("GET", HEALTH) as res:
            await client.post(url=WIDGETS)
            return res
"""
    )

    package = sample_package(resource)

    # Only an SDK or httpx client sends: a cache, headers or a client of
    # unknown kind with a route argument send nothing.
    assert sites_at(package, line_of("cache.delete", resource)) == set()
    assert sites_at(package, line_of("headers.get", resource)) == set()
    assert sites_at(package, line_of("await client.post(W", resource)) == set()
    assert sites_at(package, line_of("client.stream", resource)) == {
        ("GET", "/v1/health")
    }
    assert sites_at(package, line_of("client.post(url=", resource)) == {
        ("POST", "/v1/widgets")
    }


def test_a_helper_sends_what_its_caller_passes(sample_package):
    resource = (
        RESOURCE
        + """

async def _send(http, method, path):
    return await http.request(method, path)


async def _cached(http, path, key, cache):
    if cache.get(key):
        return None
    await http.request("POST", path)
    return await http.stream_bytes(path)


class AsyncGadgets:
    def __init__(self, http):
        self._http = http

    async def _post(self, path):
        return await self._http.request("POST", path)

    async def create(self, cache, key):
        await self._post(WIDGETS)
        await _cached(self._http, _path(key), key, cache)
        return await _send(self._http, "PATCH", path=WIDGETS)
"""
    )

    package = sample_package(resource)

    assert sites_at(package, line_of("self._post(WIDGETS)", resource)) == {
        ("POST", "/v1/widgets")
    }
    # Each client call the helper passes the path to, and no other call.
    assert sites_at(package, line_of("await _cached", resource)) == {
        ("POST", "/v1/widgets/{}"),
        ("GET", "/v1/widgets/{}"),
    }
    # The caller's literal method, where the helper passes its own on.
    assert sites_at(package, line_of('"PATCH", path=', resource)) == {
        ("PATCH", "/v1/widgets")
    }


def test_a_block_that_leaves_passes_nothing_on(sample_package):
    resource = (
        RESOURCE
        + """

async def check(http, fast, ids):
    path = WIDGETS
    if fast:
        path = _path("fast")
        return await http.request("GET", path)
    await http.request("POST", path)
    for widget_id in ids:
        if widget_id:
            path = _path(widget_id); break
        if not ids:
            raise ValueError(path)
    else:
        await http.request("PUT", path)
    await http.request("DELETE", path)
    if ids:
        path = f"{WIDGETS}/{fast}/checked"; await http.request("HEAD", path)
"""
    )

    package = sample_package(resource)

    assert sent(package, resource, '"POST", path') == {"/v1/widgets"}
    # A `break` takes its path past the `else`, even on the same line.
    assert sent(package, resource, '"PUT", path') == {"/v1/widgets"}
    assert sent(package, resource, '"DELETE", path') == {
        "/v1/widgets",
        "/v1/widgets/{}",
    }
    assert sent(package, resource, '"HEAD", path') == {
        "/v1/widgets/{}/checked"
    }


def test_helper_paths_follow_local_aliases(sample_package):
    resource = (
        RESOURCE
        + """

async def _post(http, path, alternate, flag):
    if flag:
        url = path
    else:
        url = alternate
    target = url
    return await http.request("POST", target)

async def create(http):
    await _post(http, WIDGETS, "/v1/gadgets", True)
"""
    )
    package = sample_package(resource)
    assert sites_at(package, line_of("await _post", resource)) == {
        ("POST", "/v1/widgets"),
        ("POST", "/v1/gadgets"),
    }


def test_helpers_bind_defaults_and_explicit_overrides(sample_package):
    resource = (
        RESOURCE
        + """

async def _post(http, path, method="POST"):
    return await http.request(method, path)

async def _get(http, path, *, method="GET"):
    return await http.request(method, path)

class AsyncDefaultWidgets:
    async def _send(self, path, method="PUT"):
        return await self._http.request(method, path)

    async def create(self, http):
        await _post(http, WIDGETS)
        await _get(http, WIDGETS)
        await _post(http, WIDGETS, "PATCH")
        await _get(http, WIDGETS, method="DELETE")
        await self._send(WIDGETS)
"""
    )
    package = sample_package(resource)
    for snippet, method in [
        ("await _post(http, WIDGETS)", "POST"),
        ("await _get(http, WIDGETS)", "GET"),
        ('await _post(http, WIDGETS, "PATCH")', "PATCH"),
        ('await _get(http, WIDGETS, method="DELETE")', "DELETE"),
        ("await self._send(WIDGETS)", "PUT"),
    ]:
        assert sites_at(package, line_of(snippet, resource)) == {
            (method, "/v1/widgets")
        }


def test_context_managers_can_suppress_exception_exits(sample_package):
    resource = (
        RESOURCE
        + """

import contextlib

async def suppressed(http, flag, manager):
    with contextlib.suppress(ValueError):
        path = "/v1/gadgets"
        raise ValueError()
        path = "/v1/unreachable"
    await http.request("GET", path)
    if flag:
        async with manager:
            path = "/v1/async-gadgets"
            raise ValueError()
    else:
        path = WIDGETS
    await http.request("POST", path)

async def returned(http, flag):
    path = WIDGETS
    if flag:
        with contextlib.suppress(ValueError):
            path = "/v1/returned"
            return
    await http.request("DELETE", path)
"""
    )
    package = sample_package(resource)
    assert sent(package, resource, '"GET", path') == {"/v1/gadgets"}
    assert sent(package, resource, '"POST", path') == {
        "/v1/async-gadgets",
        "/v1/widgets",
    }
    assert sent(package, resource, '"DELETE", path') == {"/v1/widgets"}
