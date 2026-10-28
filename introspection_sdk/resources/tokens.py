"""``client.tokens`` — CP ``POST /v1/tokens``: a signed-in member's access
token for one project.
"""

from __future__ import annotations

from introspection_sdk._async.resources.tokens import AsyncTokens
from introspection_sdk._sync.resources.tokens import Tokens

__all__ = ["AsyncTokens", "Tokens"]
