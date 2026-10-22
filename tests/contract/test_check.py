"""The contract check end to end, on the sample SDK and references."""

from __future__ import annotations

from api_contract.check import run
from api_contract.fields import Finding
from api_contract.report import render

from .sample import RESOURCE, SDK, line_of, references


def findings(result, operation: str) -> set[Finding]:
    return {
        f
        for problem in result.fields
        if problem.operation == operation
        for f in problem.findings
    }


def test_matching_sdk_passes(sample_package):
    result = run(sample_package(), references())

    assert not result.failed, render(result)
    assert result.operations == 5
    # The four widget operations; the CLI-only gadgets one is not expected.
    assert result.checked == 4
    assert render(result).startswith("✓ SDK surface matches")


def test_generated_sync_code_is_not_read(sample_package):
    result = run(sample_package(), references())

    assert result.unknown_route == []


def test_sdk_operation_never_called_fails(sample_package):
    specs = references()
    specs["controlplane"]["paths"]["/v1/projects"] = {
        "get": {"x-introspection": SDK, "responses": {}},
        "post": {
            "x-introspection": {"visibility": "public", "clients": ["cli"]},
            "responses": {},
        },
    }

    result = run(sample_package(), specs)

    assert result.uncalled == ["controlplane: GET /v1/projects"]
    assert "no call site in introspection_sdk/ sends it" in render(result)


def test_route_in_neither_reference_fails(sample_package):
    specs = references()
    del specs["dataplane"]["paths"]["/v1/widgets/{widget_id}"]["delete"]
    package = sample_package()

    result = run(package, specs)

    assert result.unknown_route == [
        "DELETE /v1/widgets/{} (sample_sdk/_async/widgets.py:"
        f"{line_of('_path(widget_id), expect')})"
    ]


def test_route_without_a_method_fails(sample_package):
    resource = RESOURCE + (
        "\n\ndef send(client):\n    return client.send(WIDGETS)\n"
    )

    result = run(sample_package(resource), references())

    assert result.unknown_method == [
        "/v1/widgets (sample_sdk/_async/widgets.py:"
        f"{line_of('client.send', resource)})"
    ]


def test_body_field_drift_fails(sample_package):
    specs = references()
    create = specs["dataplane"]["components"]["schemas"]["WidgetCreate"]
    create["properties"]["color"] = {"type": "string"}
    create["required"] = ["name", "size"]
    del create["properties"]["name"]

    result = run(sample_package(), specs)

    assert findings(result, "dataplane: POST /v1/widgets") == {
        Finding("missing", "body.color"),
        Finding("extra", "body.name"),
        Finding(
            "required",
            "body.size",
            "required in the reference, optional in the SDK",
        ),
    }


def test_nested_response_type_drift_fails(sample_package):
    specs = references()
    widget = specs["dataplane"]["components"]["schemas"]["Widget"]
    widget["properties"]["size"] = {"type": "string"}

    result = run(sample_package(), specs)

    expected = Finding(
        "type", "response.records[].size", "reference string, SDK number"
    )
    assert expected in findings(result, "dataplane: GET /v1/widgets")
    assert Finding(
        "type", "response.size", "reference string, SDK number"
    ) in findings(result, "dataplane: GET /v1/widgets/{widget_id}")


def test_query_parameter_drift_fails(sample_package):
    specs = references()
    params = specs["dataplane"]["paths"]["/v1/widgets"]["get"]["parameters"]
    params.append(
        {"name": "owner", "in": "query", "required": True, "schema": {}}
    )
    params[:] = [p for p in params if p["name"] != "limit"]

    result = run(sample_package(), specs)

    assert findings(result, "dataplane: GET /v1/widgets") == {
        Finding("missing", "query.owner"),
        Finding("extra", "query.limit"),
    }


def test_parameter_flagged_for_no_client_is_not_expected(sample_package):
    """`lane` carries `clients: []`: the SDK never sends it, and that is
    not drift."""
    result = run(sample_package(), references())

    assert findings(result, "dataplane: GET /v1/widgets") == set()


def test_untyped_call_site_warns_without_failing(sample_package):
    resource = RESOURCE.replace(
        "json=WidgetCreate(name=name, size=size).model_dump()",
        "json=self.body(name)",
    ).replace(
        "    async def get(",
        "    def body(self, name):\n        return {}\n\n    async def get(",
    )

    result = run(sample_package(resource), references())

    assert not result.failed, render(result)
    [warning] = result.warnings
    assert warning.operation == "dataplane: POST /v1/widgets"
    assert warning.field == "body"
    call = line_of('"POST", WIDGETS', resource) - 1
    assert warning.at == f"sample_sdk/_async/widgets.py:{call}"
    assert "Warning: SDK has no concrete types" in render(result)


RAW_GET = RESOURCE.replace(
    """        return Widget.model_validate(
            await self._http.request("GET", _path(widget_id))
        )""",
    """        response = await self._http.request(
            "GET", _path(widget_id), expect="raw"
        )
        assert isinstance(response, bytes)
        return _widget(response)""",
).replace(
    "class AsyncWidgets:",
    "def _widget(response: Any) -> Widget | None:\n"
    "    if not response.content:\n"
    "        return None\n"
    "    return Widget.model_validate_json(response.content)\n\n\n"
    "class AsyncWidgets:",
)


def test_raw_response_parsed_as_json_is_compared(sample_package):
    specs = references()
    widget = specs["dataplane"]["components"]["schemas"]["Widget"]
    widget["properties"]["size"] = {"type": "string"}

    result = run(sample_package(RAW_GET), specs)

    assert Finding(
        "type", "response.size", "reference string, SDK number"
    ) in findings(result, "dataplane: GET /v1/widgets/{widget_id}")


def test_raw_response_nothing_parses_warns(sample_package):
    resource = RAW_GET.replace(
        "        response = await", "        await"
    ).replace("        return _widget(response)", "        return None")

    result = run(sample_package(resource), references())

    assert not result.failed, render(result)
    [warning] = result.warnings
    assert warning.operation == "dataplane: GET /v1/widgets/{widget_id}"
    assert warning.field == "response"


def test_raw_response_of_another_media_type_is_not_compared(sample_package):
    resource = RAW_GET.replace(
        'expect="raw"',
        'headers={"Accept": "application/octet-stream"}, expect="raw"',
    )

    result = run(sample_package(resource), references())

    assert findings(result, "dataplane: GET /v1/widgets/{widget_id}") == set()
    assert result.warnings == []
