"""``client.connectors`` — CP namespace for ``/v1/connectors``.

Connectors are provider integrations (Slack, Gmail, Stripe, ...) a
project owns. The connections granted through them are read and
deleted on the data plane (``client.connections``). ``authorize`` mints the
consent URL a Business hands its customer — the SDK presents it as a
connector operation even though the route lives under ``/v1/oauth/``.

``client_secret`` / ``signing_secret`` are write-only: accepted on
create and update, absent from every response, and omitting them on
update means "unchanged". A ``webhook`` connector is the exception: it
is created without a secret, and the platform generates each one and
returns it once, on ``update(rotate_signing_secret="standard_webhooks")``
(or ``"bearer"``) for the first and ``update(rotate_signing_secret=True)``
for a rotation; the secret a rotation replaces stays valid until
``update(revoke_signing_secret=<kid>)``.
Project scope comes from the authenticated credential; connector calls do not
take a separate project selector.
"""

from __future__ import annotations

from introspection_sdk._async.resources.connectors import AsyncConnectors
from introspection_sdk._sync.resources.connectors import Connectors

__all__ = [
    "AsyncConnectors",
    "Connectors",
]
