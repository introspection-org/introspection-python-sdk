"""The contract check end to end, on the sample SDK and references."""

from __future__ import annotations

from api_contract.check import run

from .sample import RESOURCE, SDK, line_of, references


def test_matching_sdk_passes(sample_package):
    result = run(sample_package(), references())

    assert not result.failed(), result.render()
    # The CLI-only gadgets operation is not expected of the SDK.
    assert result.operations == 5
    assert result.render().startswith("✓ SDK routes match")


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
    assert "no call site in introspection_sdk/ sends it" in result.render()
    assert "1 sdk operations never called" in result.render()
    # A pull request only reports it.
    assert not result.failed(full=False)
    assert "reported only, never fails a PR" in result.render(full=False)


def test_route_in_neither_reference_fails(sample_package):
    specs = references()
    del specs["dataplane"]["paths"]["/v1/widgets/{widget_id}"]["delete"]

    result = run(sample_package(), specs)

    assert result.failed(full=False)
    assert result.unknown_route == [
        "DELETE /v1/widgets/{} (sample_sdk/_async/widgets.py:"
        f"{line_of('_path(widget_id), expect')})"
    ]


def test_route_without_a_method_fails_as_unknown(sample_package):
    resource = RESOURCE + (
        "\n\ndef send(client, verb):\n"
        "    return client.request(verb, WIDGETS)\n"
    )

    result = run(sample_package(resource), references())

    assert result.unknown_route == [
        "? /v1/widgets (sample_sdk/_async/widgets.py:"
        f"{line_of('client.request(verb', resource)})"
    ]
