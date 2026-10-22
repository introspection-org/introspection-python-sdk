"""Reading the references: operations, their flags, and their shapes."""

from __future__ import annotations

import json

import pytest
from api_contract.reference import (
    DEFAULT_URLS,
    Operation,
    load_reference,
    operations,
    reference_source,
    shapes,
    template_key,
)

from .sample import DATAPLANE


def test_template_key_compares_path_parameters_by_position():
    assert template_key("/v1/tags/{kind}/{name}") == "/v1/tags/{}/{}"
    assert template_key("/v1/a/{x}/b") == template_key("/v1/a/{}/b")


def test_operations_carry_their_clients():
    ops = {op.key: op for op in operations("dataplane", DATAPLANE)}

    assert ops["GET /v1/widgets"].clients == ("sdk",)
    assert ops["GET /v1/gadgets"].clients == ("cli",)
    assert ops["DELETE /v1/widgets/{}"].name == (
        "dataplane: DELETE /v1/widgets/{widget_id}"
    )


def test_shapes_leave_out_parameters_no_client_sends():
    op = Operation("dataplane", "GET", "/v1/widgets", ("sdk",))

    got = shapes(DATAPLANE, op)

    assert set(got.query["properties"]) == {"name", "limit"}
    assert got.body_media == ()
    assert "application/json" in got.response


def test_shapes_follow_response_and_body_refs():
    op = Operation("dataplane", "POST", "/v1/widgets", ("sdk",))

    got = shapes(DATAPLANE, op)

    assert got.body_required
    assert got.body_schema == {"$ref": "#/components/schemas/WidgetCreate"}
    assert got.response["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Widget"
    }


def test_reference_source_prefers_flag_then_env_then_staging(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("API_CONTRACT_DATAPLANE", raising=False)
    assert reference_source("dataplane") == DEFAULT_URLS["dataplane"]
    assert DEFAULT_URLS["dataplane"].startswith(
        "https://api.staging.introspection.dev/"
    )

    monkeypatch.setenv("API_CONTRACT_DATAPLANE", "/tmp/dp.json")
    assert reference_source("dataplane") == "/tmp/dp.json"
    assert reference_source("dataplane", "dp.json") == "dp.json"


def test_load_reference_reads_a_local_file(tmp_path):
    path = tmp_path / "dataplane.json"
    path.write_text(json.dumps(DATAPLANE))

    assert load_reference(str(path)) == DATAPLANE
