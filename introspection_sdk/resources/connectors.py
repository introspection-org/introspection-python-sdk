"""``client.connectors`` — CP namespace for ``/v1/connectors``.

Connectors are provider integrations (Slack, Gmail, Stripe, ...) a
project owns. The connections granted through them are read and
deleted on the data plane (``client.connections``). ``authorize`` mints the
consent URL a Business hands its customer — the SDK presents it as a
connector operation even though the route lives under ``/v1/oauth/``.

``client_secret`` / ``signing_secret`` are write-only: accepted on
create and update, absent from every response, and omitting them on
update means "unchanged". A ``webhook`` connector is the exception: it
is created without a secret, and its secrets are the ``secrets``
sub-resource (``/v1/connectors/{id}/secrets``). The platform generates
each one and returns it once, on ``secrets.create(id, type=...)`` for the
first and ``secrets.create(id)`` for a rotation; the secret a rotation
replaces stays valid until ``secrets.delete(id, kid)``.
Project scope comes from the authenticated credential; connector calls do not
take a separate project selector.
"""

from __future__ import annotations

from introspection_sdk._async.resources.connectors import (
    AsyncConnectors,
    AsyncConnectorSecrets,
)
from introspection_sdk._sync.resources.connectors import (
    Connectors,
    ConnectorSecrets,
)

__all__ = [
    "AsyncConnectorSecrets",
    "AsyncConnectors",
    "ConnectorSecrets",
    "Connectors",
]
