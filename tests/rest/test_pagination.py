"""Tests for the generic :class:`introspection_sdk.pagination.Pager`.

The Pager is the single object every ``list()`` returns: it is iterable
(streams every item across pages, fetched lazily) and exposes the first
page's envelope via ``.page()`` (and proxied attribute access). These
tests exercise that dual-mode behaviour directly through the offline
``FakeAPI`` transport.
"""

from __future__ import annotations

import httpx

from introspection_sdk.runner_resources.tasks import Tasks

from .conftest import FakeAPI, paginated, task_payload, to_jsonable


def _tasks(fake_api: FakeAPI) -> Tasks:
    return Tasks(fake_api.client())


def _two_pages(fake_api: FakeAPI) -> None:
    pages = iter(
        [
            paginated([task_payload(title="a")], next="cursor-2"),
            paginated([task_payload(title="b")]),
        ]
    )

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=to_jsonable(next(pages)))

    fake_api.add_handler("GET", "/v1/tasks", handler)


def test_list_is_lazy_no_request_until_used(fake_api: FakeAPI):
    fake_api.add("GET", "/v1/tasks", json_body=paginated([task_payload()]))
    pager = _tasks(fake_api).list()
    # Constructing the Pager issues no request.
    assert fake_api.requests == []
    pager.page()
    assert len(fake_api.requests) == 1


def test_page_returns_first_page_only_and_caches(fake_api: FakeAPI):
    _two_pages(fake_api)
    pager = _tasks(fake_api).list()
    page = pager.page()
    assert page.next == "cursor-2"
    assert [t.title for t in page.records] == ["a"]
    # Repeated .page() is cached — still exactly one request.
    assert pager.page() is page
    assert len(fake_api.requests) == 1


def test_iteration_streams_every_item_across_pages(fake_api: FakeAPI):
    _two_pages(fake_api)
    titles = [t.title for t in _tasks(fake_api).list()]
    assert titles == ["a", "b"]
    assert len(fake_api.requests) == 2
    assert fake_api.requests[1].params.get("next") == "cursor-2"


def test_attribute_access_is_proxied_to_first_page(fake_api: FakeAPI):
    fake_api.add(
        "GET",
        "/v1/tasks",
        json_body=paginated([task_payload()], total_count=7),
    )
    pager = _tasks(fake_api).list(include_total=True)
    # Envelope fields are reachable directly on the Pager (proxied to the
    # lazily-fetched, cached first page).
    assert pager.total_count == 7
    assert pager.count == 1
    assert len(fake_api.requests) == 1


def test_iteration_stops_early_without_fetching_more(fake_api: FakeAPI):
    _two_pages(fake_api)
    first = next(iter(_tasks(fake_api).list()))
    assert first.title == "a"
    # Stopping after the first item must not fetch page two.
    assert len(fake_api.requests) == 1
