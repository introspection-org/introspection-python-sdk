"""HTTP transports for Introspection credential-injecting egress.

Choose the adapter matching the client library explicitly::

    from introspection_sdk.proxy.httpx2 import IntrospectionTransport
    from introspection_sdk.proxy.httpx import IntrospectionTransport
"""

from introspection_sdk.proxy._config import ProxyConfig

__all__ = ["ProxyConfig"]
