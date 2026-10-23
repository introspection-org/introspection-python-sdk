"""Finally runs on exiting paths without making those paths fall through."""

from textwrap import indent

import pytest

from .sample import RESOURCE
from .test_routes import sent


@pytest.mark.parametrize(
    "body",
    [
        "return",
        "raise ValueError()",
        "try:\n    pass\nfinally:\n    return",
        "try:\n    pass\nexcept ValueError:\n    return\nelse:\n    return",
        "try:\n    return\nexcept ValueError:\n    return",
    ],
)
def test_finally_on_exiting_branch_does_not_reach_later_call(
    sample_package, body
):
    resource = (
        RESOURCE
        + f"""

async def act(http, flag):
    if flag:
        try:
{indent(body, "            ")}
        finally:
            path = "/v1/gadgets"
            await http.request("PATCH", path)
        path = "/v1/unreachable"
    else:
        path = WIDGETS
    await http.request("GET", path)
"""
    )
    package = sample_package(resource)
    assert sent(package, resource, '"GET", path') == {"/v1/widgets"}
    # Finally itself still runs, including when the try body returns.
    assert sent(package, resource, '"PATCH", path') == {"/v1/gadgets"}


@pytest.mark.parametrize(
    "body",
    [
        "pass",
        "if flag:\n    return",
        "try:\n    return\nexcept ValueError:\n    pass",
        "try:\n    pass\nexcept* ValueError:\n    pass",
    ],
)
def test_finally_can_assign_first_value_on_completing_path(
    sample_package, body
):
    resource = (
        RESOURCE
        + f"""

async def act(http, flag):
    try:
{indent(body, "        ")}
    finally:
        path = "/v1/gadgets"
    await http.request("GET", path)
"""
    )
    package = sample_package(resource)
    assert sent(package, resource, '"GET", path') == {"/v1/gadgets"}


def test_finally_return_overrides_normal_completion(sample_package):
    resource = (
        RESOURCE
        + """

async def act(http, flag):
    if flag:
        try:
            path = "/v1/gadgets"
        finally:
            return
    else:
        path = WIDGETS
    await http.request("GET", path)
"""
    )
    package = sample_package(resource)
    assert sent(package, resource, '"GET", path') == {"/v1/widgets"}
