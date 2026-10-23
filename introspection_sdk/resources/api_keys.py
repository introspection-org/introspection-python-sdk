"""``client.api_keys`` — CP namespace for ``/v1/api-keys``.

A project's API keys. Needs an org credential (a member session or access
token); a project API key cannot manage keys. The plaintext of a new key is
returned once, as a ``SecretStr``.
"""

from __future__ import annotations

from introspection_sdk._async.resources.api_keys import (
    AsyncApiKeys,
)
from introspection_sdk._sync.resources.api_keys import (
    ApiKeys,
)

__all__ = [
    "ApiKeys",
    "AsyncApiKeys",
]
