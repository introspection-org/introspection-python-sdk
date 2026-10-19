"""Helpers shared by the live walks."""

from __future__ import annotations

import os
import secrets
import time
from uuid import UUID

import pytest


def uuid7() -> UUID:
    """A UUIDv7; ``uuid.uuid7`` is 3.14+ and this package supports 3.11."""
    value = (
        (int(time.time() * 1000) & ((1 << 48) - 1)) << 80
    ) | secrets.randbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return UUID(int=value)


def setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set")
    return value


def unique(prefix: str) -> str:
    """A name no other run shares, so concurrent runs never collide and a
    leftover from a crashed run is recognisable."""
    return f"sdk-{prefix}-{uuid7().hex}"
