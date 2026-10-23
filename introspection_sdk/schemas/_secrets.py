"""Secrets the API returns once or takes on write.

Both directions use pydantic's :class:`~pydantic.SecretStr`, so ``repr``,
``str`` and logging print ``**********`` rather than the plaintext; read it
with ``.get_secret_value()``. :data:`WireSecret` is the request-body form: it
serializes to the plaintext in a JSON dump, which is the one place it has to
appear.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import PlainSerializer, SecretStr

WireSecret = Annotated[
    SecretStr,
    PlainSerializer(
        lambda value: value.get_secret_value(),
        return_type=str,
        when_used="json",
    ),
]
