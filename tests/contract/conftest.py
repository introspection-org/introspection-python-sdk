from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from api_contract.source import Package

from .sample import RESOURCE, write_sdk


@pytest.fixture
def sample_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., Package]]:
    """Writes the sample SDK (optionally with another resource module) and
    loads it as the checker would, importable for its runtime types."""
    monkeypatch.syspath_prepend(str(tmp_path))

    def load(resource: str = RESOURCE) -> Package:
        write_sdk(tmp_path, resource)
        return Package.load(tmp_path, "sample_sdk")

    yield load
    for name in [m for m in sys.modules if m.startswith("sample_sdk")]:
        del sys.modules[name]
