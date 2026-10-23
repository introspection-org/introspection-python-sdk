"""Picking the staging reference URLs: dispatch payload, manual inputs, the
recorded pair, and the failure when none of them names both."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_contract.urls import CACHE_FILE, MissingUrls, ReferenceUrls, resolve
from resolve_api_reference_urls import main

CP = "https://api.cp.example"
DP = "https://api.dp.example"
NONE = ("", "")


def record(cache: Path, cp_url: str, dp_url: str) -> None:
    ReferenceUrls(cp_url, dp_url, "payload").save(cache)


def test_the_payload_wins_over_inputs_and_cache(tmp_path):
    record(tmp_path, "https://old.cp", "https://old.dp")

    urls = resolve(
        (CP + "/", DP), ("https://in.cp", "https://in.dp"), tmp_path
    )

    assert urls == ReferenceUrls(CP, DP, "payload")


def test_inputs_win_over_the_cache(tmp_path):
    record(tmp_path, "https://old.cp", "https://old.dp")

    assert resolve(NONE, (CP, DP), tmp_path) == ReferenceUrls(CP, DP, "input")


def test_without_payload_or_inputs_the_recorded_pair_is_used(tmp_path):
    record(tmp_path, CP, DP)

    assert resolve(NONE, (" ", ""), tmp_path) == ReferenceUrls(CP, DP, "cache")


def test_nothing_recorded_fails_saying_how_to_record_a_pair(tmp_path):
    with pytest.raises(MissingUrls) as error:
        resolve(NONE, NONE, tmp_path)

    message = str(error.value)
    assert message.startswith("no staging reference URLs recorded yet")
    assert '"API Reference Deployed"' in message
    assert "cp_url and dp_url" in message


@pytest.mark.parametrize(
    "case",
    [
        ((CP, ""), NONE, "the payload names no dp_url"),
        (NONE, ("", DP), "the input names no cp_url"),
        (NONE, ("api.cp.example", DP), "input cp_url is not an http"),
        (NONE, (CP, DP + "\nX=1"), "input dp_url is not an http"),
    ],
)
def test_a_half_or_malformed_pair_is_an_error(tmp_path, case):
    payload, inputs, message = case
    record(tmp_path, CP, DP)

    with pytest.raises(ValueError, match=message):
        resolve(payload, inputs, tmp_path)


@pytest.fixture
def github(tmp_path, monkeypatch) -> dict[str, Path]:
    files = {"env": tmp_path / "env", "output": tmp_path / "output"}
    monkeypatch.setenv("GITHUB_ENV", str(files["env"]))
    monkeypatch.setenv("GITHUB_OUTPUT", str(files["output"]))
    for source in ("PAYLOAD", "INPUT"):
        for plane in ("CP", "DP"):
            monkeypatch.delenv(f"{source}_{plane}_URL", raising=False)
    return files


def test_a_dispatch_exports_and_records_its_pair(
    tmp_path, monkeypatch, github
):
    cache = tmp_path / "cache"
    monkeypatch.setenv("PAYLOAD_CP_URL", CP)
    monkeypatch.setenv("PAYLOAD_DP_URL", DP)

    assert main([str(cache)]) == 0
    assert github["env"].read_text() == (
        f"INTROSPECTION_CP_URL={CP}\nINTROSPECTION_DP_URL={DP}\n"
    )
    assert github["output"].read_text() == "source=payload\n"
    saved = json.loads((cache / CACHE_FILE).read_text())
    assert saved == {"cp_url": CP, "dp_url": DP}


def test_inputs_are_exported_but_not_recorded(tmp_path, monkeypatch, github):
    cache = tmp_path / "cache"
    monkeypatch.setenv("INPUT_CP_URL", CP)
    monkeypatch.setenv("INPUT_DP_URL", DP)

    assert main([str(cache)]) == 0
    assert github["output"].read_text() == "source=input\n"
    assert not cache.exists()


def test_a_cache_miss_exits_2_and_exports_nothing(tmp_path, github, capsys):
    cache = tmp_path / "cache"

    assert main([str(cache)]) == 2
    out = capsys.readouterr().out
    assert "::error::could not pick the API reference URLs: no staging" in out
    assert not github["env"].exists()
    assert not github["output"].exists()
    assert not cache.exists()
