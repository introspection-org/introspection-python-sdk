"""Re-exported by :mod:`introspection_sdk.runner_resources.remotes`."""

from __future__ import annotations

from introspection_sdk._async.resources._crud import _AsyncResource
from introspection_sdk.schemas.remotes import RemotesConnectDocs

#: The path a remote opens its WebSocket on.
REMOTES_CONNECT_PATH = "/v1/remotes/connect"


class AsyncRemotes(_AsyncResource):
    """DP ``/v1/remotes``: the dial-out connection ``introspection dev``
    attaches a local remote over."""

    async def connect_docs(self) -> RemotesConnectDocs:
        """Read the ``/v1/remotes/connect`` WebSocket's protocol: how it
        authenticates, its handshake and the frames each side sends. A
        remote opens the WebSocket on the same path."""
        return await self._call(
            "GET", REMOTES_CONNECT_PATH, RemotesConnectDocs
        )
