"""``client.endpoints`` — CP ``/v1/endpoints``: the upstream hosts a
project's runtimes reach, an MCP server's binding among them.
"""

from __future__ import annotations

from introspection_sdk._async.resources.endpoints import AsyncEndpoints
from introspection_sdk._sync.resources.endpoints import Endpoints

__all__ = ["AsyncEndpoints", "Endpoints"]
