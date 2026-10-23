"""Reading the references: operations and their flags."""

from __future__ import annotations

import json

import pytest
from api_contract.reference import (
    CONTROLPLANE_URL,
    MissingDataplaneUrl,
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


def test_reference_source_prefers_flag_then_env_then_staging(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("API_CONTRACT_CONTROLPLANE", raising=False)
    monkeypatch.delenv("API_CONTRACT_DATAPLANE", raising=False)
    monkeypatch.setenv("STAGING_DP_URL", "https://api.dp.example/")
    assert reference_source("controlplane") == CONTROLPLANE_URL
    assert CONTROLPLANE_URL.endswith("/openapi.json")
    assert (
        reference_source("dataplane") == "https://api.dp.example/openapi.json"
    )

    monkeypatch.setenv("API_CONTRACT_DATAPLANE", "/tmp/dp.json")
    assert reference_source("dataplane") == "/tmp/dp.json"
    assert reference_source("dataplane", "dp.json") == "dp.json"


@pytest.mark.parametrize("value", [None, "", "  "])
def test_dataplane_without_staging_dp_url_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, value
):
    monkeypatch.delenv("API_CONTRACT_DATAPLANE", raising=False)
    if value is None:
        monkeypatch.delenv("STAGING_DP_URL", raising=False)
    else:
        monkeypatch.setenv("STAGING_DP_URL", value)

    with pytest.raises(MissingDataplaneUrl, match="STAGING_DP_URL"):
        reference_source("dataplane")


def test_load_reference_reads_a_local_file(tmp_path):
    path = tmp_path / "dataplane.json"
    path.write_text(json.dumps(DATAPLANE))

    assert load_reference(str(path)) == DATAPLANE
