"""The walk's one cassette, its mode, its step runner and its report.

One cassette for the module, held across every step: per-test cassettes
(pytest-recording's ``@pytest.mark.vcr``) would reload the HAR per test and
reset what it has played, so identical requests would no longer be consumed
in recorded order. The VCR instance is pytest-recording's kind, configured
through its ``pytest_recording_configure`` hook, and its record mode follows
``VCR_MODE`` (mirroring ``POLLY_MODE``) or pytest-recording's flags:

- ``replay`` (default; ``--record-mode=none``): record mode ``none``; a
  request with no recorded match fails the step, naming method, URL and the
  body diff.
- ``record`` (``--record-mode=all`` or ``rewrite``): a live run against the
  target writes a fresh ``tests/recordings/walk/recording.har``, scrubbed.
- ``passthrough`` (``--disable-recording``): live, records nothing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import vcr
from vcr.cassette import Cassette
from vcr.record_mode import RecordMode

from . import har
from .matching import (
    MATCH_ON,
    scrub_request,
    scrub_response,
    semantic_body,
    semantic_query,
)
from .settings import RECORDINGS_DIR, Mode, walk_mode
from .support import WalkReport, has_complete_recording

HAR = RECORDINGS_DIR / "walk" / "recording.har"
REPORT = Path(
    os.environ.get(
        "WALK_REPORT",
        Path(__file__).parents[2] / "generated" / "walk-report.json",
    )
)


def _mode(config: pytest.Config) -> Mode:
    if config.getoption("--disable-recording", default=False):
        return "passthrough"
    flag = config.getoption("--record-mode", default=None)
    if flag in ("all", "rewrite", "new_episodes"):
        return "record"
    if flag == "none":
        return "replay"
    return walk_mode()


@pytest.fixture(scope="session")
def mode(pytestconfig: pytest.Config) -> Mode:
    return _mode(pytestconfig)


def walk_vcr(
    pytestconfig: pytest.Config,
    record_mode: RecordMode,
    directory: Path = HAR.parent,
) -> vcr.VCR:
    """A VCR configured for the walk's HAR (see the module)."""
    instance = vcr.VCR(
        cassette_library_dir=str(directory),
        serializer="har",
        record_mode=record_mode,
        match_on=MATCH_ON,
        before_record_request=scrub_request,
        before_record_response=scrub_response,
        decode_compressed_response=True,
    )
    instance.register_serializer("har", har)
    instance.register_matcher("semantic_body", semantic_body)
    instance.register_matcher("semantic_query", semantic_query)
    pytestconfig.hook.pytest_recording_configure(
        config=pytestconfig, vcr=instance
    )
    return instance


def _consumption(cassette: Cassette, report: WalkReport) -> None:
    report.total = len(cassette.data)
    report.consumed = sum(
        1 for i in range(report.total) if cassette.play_counts[i]
    )
    report.unconsumed = [
        {"method": request.method, "url": request.uri}
        for i, (request, _) in enumerate(cassette.data)
        if not cassette.play_counts[i]
    ]


@pytest.fixture(scope="module")
def report() -> WalkReport:
    return WalkReport()


@pytest.fixture(scope="module")
def cassette(
    pytestconfig: pytest.Config, mode: Mode, report: WalkReport
) -> Iterator[Cassette | None]:
    """The module's one cassette; the run report is written as it closes."""
    if mode == "replay" and not has_complete_recording(HAR):
        pytest.skip(f"{HAR} does not reach the walk's teardown")
    if mode == "passthrough":
        yield None
        report.write(REPORT)
        return
    if mode == "record":
        HAR.unlink(missing_ok=True)
    record_mode = RecordMode.ALL if mode == "record" else RecordMode.NONE
    with walk_vcr(pytestconfig, record_mode).use_cassette(
        HAR.name, allow_playback_repeats=False
    ) as tape:
        yield tape
        if mode == "replay":
            _consumption(tape, report)
    report.write(REPORT)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Iterator[None]:
    result: pytest.TestReport = yield
    walk_report = getattr(item, "walk_report", None)
    step = getattr(item, "walk_step", None)
    if walk_report is None or step is None:
        return result
    if result.when == "setup" and result.skipped:
        walk_report.steps.append({**step, "status": "skipped"})
    elif result.when == "call":
        status = (
            "passed"
            if result.passed
            else ("skipped" if result.skipped else "failed")
        )
        walk_report.steps.append({**step, "status": status})
        if result.failed and walk_report.failed is None:
            walk_report.failed = step["name"]
    return result


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "walk_step(n, name): the walk step a test is"
    )
