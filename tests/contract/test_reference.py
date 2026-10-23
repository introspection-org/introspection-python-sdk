"""Reading the references: operations and their flags."""

from __future__ import annotations

import json

import pytest
from api_contract.reference import (
    MissingBaseUrl,
    load_reference,
    operations,
    reference_source,
    template_key,
)

from .sample import DATAPLANE


def test_template_key_compares_path_parameters_by_position():
    assert template_key("/v1/tags/{kind}/{name}") == "/v1/tags/{}/{}"
    assert template_key("/v1/a/{x}/b") == template_key("/v1/a/{}/b")


def test_operations_carry_their_clients():
    ops = {op.key: op for op in operations("dataplane", DATAPLANE)}

    assert ops["POST /v1/widgets"].clients == ("sdk",)
    assert ops["GET /v1/gadgets"].clients == ("cli",)
    # No x-introspection is no restriction; [] is no client.
    assert ops["GET /v1/widgets"].clients is None
    assert ops["GET /v1/widgets"].wanted_by("sdk")
    assert ops["DELETE /v1/gadgets"].clients == ()
    assert not ops["DELETE /v1/gadgets"].wanted_by("sdk")
    assert not ops["GET /v1/gadgets"].wanted_by("sdk")
    assert ops["DELETE /v1/widgets/{}"].name == (
        "dataplane: DELETE /v1/widgets/{widget_id}"
    )


def test_reference_source_prefers_flag_then_base_url(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("INTROSPECTION_CP_URL", "https://api.cp.example")
    monkeypatch.setenv("INTROSPECTION_DP_URL", " https://api.dp.example/ ")
    assert (
        reference_source("controlplane")
        == "https://api.cp.example/openapi.json"
    )
    assert (
        reference_source("dataplane") == "https://api.dp.example/openapi.json"
    )
    assert reference_source("dataplane", "dp.json") == "dp.json"


@pytest.mark.parametrize(
    "case",
    [
        (plane, var, value)
        for plane, var in (
            ("controlplane", "INTROSPECTION_CP_URL"),
            ("dataplane", "INTROSPECTION_DP_URL"),
        )
        for value in (None, "", "  ")
    ],
)
def test_an_unset_base_url_names_the_variable_and_the_flag(
    monkeypatch: pytest.MonkeyPatch, case
):
    plane, var, value = case
    if value is None:
        monkeypatch.delenv(var, raising=False)
    else:
        monkeypatch.setenv(var, value)

    with pytest.raises(MissingBaseUrl, match=f"{var} is unset.*--{plane}"):
        reference_source(plane)


def test_load_reference_reads_a_local_file(tmp_path):
    path = tmp_path / "dataplane.json"
    path.write_text(json.dumps(DATAPLANE))

    assert load_reference(str(path)) == DATAPLANE
