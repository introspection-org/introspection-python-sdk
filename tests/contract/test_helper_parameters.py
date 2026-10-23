"""Incoming helper parameters survive only the paths that preserve them."""

from textwrap import indent

import pytest

from .sample import RESOURCE, line_of
from .test_routes import sites_at


@pytest.mark.parametrize(
    ("body", "keeps_incoming"),
    [
        ("if flag:\n    path = fallback", True),
        ("if flag:\n    pass\nelse:\n    path = fallback", True),
        ("match flag:\n    case True:\n        path = fallback", True),
        ("for item in flag:\n    path = fallback", True),
        ("while flag:\n    path = fallback", True),
        ("path = fallback", False),
        ("if flag:\n    path = fallback\nelse:\n    path = fallback", False),
        ("if flag:\n    path = fallback\nelse:\n    return", False),
        (
            "if flag:\n    path = fallback\nelse:\n    raise ValueError()",
            False,
        ),
    ],
)
@pytest.mark.parametrize("alias", ["path", "target"])
def test_helper_parameter_reaching_branches(
    sample_package, body, keeps_incoming, alias
):
    resource = (
        RESOURCE
        + f"""

async def _post(http, path, fallback, flag):
{indent(body, "    ")}
    target = path
    return await http.request("POST", {alias})

async def create(http, flag):
    await _post(http, WIDGETS, "/v1/gadgets", flag)
"""
    )
    package = sample_package(resource)
    expected = {("POST", "/v1/gadgets")}
    if keeps_incoming:
        expected.add(("POST", "/v1/widgets"))
    assert sites_at(package, line_of("await _post", resource)) == expected
