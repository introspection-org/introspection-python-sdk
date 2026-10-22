"""Who a Person Server speaks for: the person a `login_hint` names in a tenant."""

from __future__ import annotations

from typing import Protocol


class Directory(Protocol):
    def person(self, login_hint: str, tenant: str) -> str | None:
        """The person a `login_hint` names in `tenant`, or None if this Person
        Server does not speak for them."""
        ...


class AnyoneDirectory:
    """Speaks for whoever the hint names: for samples and tests."""

    def person(self, login_hint: str, tenant: str) -> str | None:
        return login_hint or None
