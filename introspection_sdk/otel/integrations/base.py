"""Integration base class, modeled on sentry_sdk's integration registry."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod

from opentelemetry.sdk.trace import TracerProvider

__all__ = ["Integration", "DidNotEnable"]


class DidNotEnable(Exception):
    """Integration could not activate (framework missing, version too old, ...).

    Swallowed during auto-discovery; re-raised when requested explicitly.
    """


class Integration(ABC):
    """Base class for framework integrations wired up by ``init()``.

    ``deactivates`` names other integrations to disable when this one is active,
    so a wrapping framework (e.g. LangChain) doesn't double-trace the SDK it wraps.
    """

    identifier: str
    min_version: tuple[int, ...] | None = None
    deactivates: frozenset[str] = frozenset()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        identifier = getattr(cls, "identifier", None)
        if not isinstance(identifier, str) or not identifier:
            raise TypeError(
                f"{cls.__name__} must define a non-empty class-level "
                f"'identifier: str'"
            )
        # getattr_static inspects the raw descriptor without binding it.
        setup = inspect.getattr_static(cls, "setup_once", None)
        if setup is not None and not isinstance(setup, staticmethod):
            raise TypeError(
                f"{cls.__name__}.setup_once must be a @staticmethod "
                f"(the loader calls it at the class level)"
            )

    @staticmethod
    @abstractmethod
    def setup_once(*, tracer_provider: TracerProvider) -> None:
        """Wire the framework into ``tracer_provider``. Runs once; may raise DidNotEnable."""
