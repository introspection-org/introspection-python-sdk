"""Pydantic mirrors of DP ``GET /v1/remotes/connect``: the protocol of the
WebSocket ``introspection dev`` dials out on.

Wire fields are snake_case verbatim and unknown fields are tolerated
via ``extra="allow"`` so DP additions don't break the SDK.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class WsAuthenticationDocs(ApiModel):
    """How a socket authenticates."""

    method: str
    description: str
    example: str


class WsFrameDocs(ApiModel):
    """One frame of the wire protocol; ``frame`` names the protobuf
    ``Frame.body`` oneof field."""

    frame: str
    description: str


class WsMessageProtocolDocs(ApiModel):
    """The frames each side sends."""

    remote_to_cloud: list[WsFrameDocs]
    cloud_to_remote: list[WsFrameDocs]


class RemotesConnectDocs(ApiModel):
    """The ``/v1/remotes/connect`` WebSocket, described: its path,
    authentication, handshake, schema version, encoding and frames."""

    endpoint: str
    protocol: str
    authentication: WsAuthenticationDocs
    handshake: list[str]
    schema_version: int
    encoding: str
    message_protocol: WsMessageProtocolDocs


__all__ = [
    "RemotesConnectDocs",
    "WsAuthenticationDocs",
    "WsFrameDocs",
    "WsMessageProtocolDocs",
]
