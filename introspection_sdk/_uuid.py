"""UUIDv7 minting shared by the request bodies that carry a client id."""

from __future__ import annotations

import secrets
import time
from uuid import UUID


def _uuid7() -> UUID:
    """Mint a UUIDv7 without depending on Python 3.14's ``uuid.uuid7``."""
    value = (
        (int(time.time() * 1000) & ((1 << 48) - 1)) << 80
    ) | secrets.randbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return UUID(int=value)
