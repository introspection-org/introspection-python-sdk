from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from api_contract.source import Package

from .sample import RESOURCE, write_sdk


@pytest.fixture
def sample_package(tmp_path: Path) -> Callable[..., Package]:
    """Writes the sample SDK (optionally with another resource module) and
    loads it as the checker would."""

    def load(resource: str = RESOURCE) -> Package:
        write_sdk(tmp_path, resource)
        return Package.load(tmp_path, "sample_sdk")

    return load
