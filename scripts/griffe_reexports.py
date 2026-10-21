"""Griffe extension: check a re-exported public object as the object itself.

``griffe check`` compares a public name that changed from a class to a
re-export of it (``introspection_sdk.client.IntrospectionClient`` moving into
``_sync/`` behind an import, say) without comparing any of its members:
``_type_based_yield`` records the old object's path in ``seen_paths`` before
it resolves the alias, then recurses into the target with that same old
path and returns at once. Removing a parameter from such a class passes the
check. griffe has no option for this, so this extension swaps every public
alias whose target lives in the same package for the target object before
the check runs. Both sides then hold the real objects, and the breakage
rules apply to them as they do to a class that never moved.

Loaded by ``griffe check -e scripts/griffe_reexports.py``, on the old
release and the new code alike.
"""

from __future__ import annotations

from typing import Any

from griffe import (
    Alias,
    AliasResolutionError,
    Class,
    CyclicAliasError,
    Extension,
    GriffeLoader,
    Module,
)


class InlineReexports(Extension):
    """Replace each public in-package alias with the object it points to."""

    def on_package(
        self, *, pkg: Module, loader: GriffeLoader, **kwargs: Any
    ) -> None:
        _inline(pkg, pkg)


def _inline(obj: Module | Class, pkg: Module) -> None:
    for name, member in list(obj.members.items()):
        if isinstance(member, Alias):
            if not member.is_public:
                continue
            try:
                target = member.final_target
            except (AliasResolutionError, CyclicAliasError):
                continue
            if target.package is not pkg:
                continue
            # The target's own module is often private (`_sync/`); it is
            # public here because this module exports it.
            target.public = True
            obj.members[name] = target
        elif isinstance(member, (Module, Class)):
            _inline(member, pkg)
