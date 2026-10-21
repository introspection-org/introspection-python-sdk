"""``client.experiments`` — CP CRUD + lifecycle + ``.run()`` returning a
:class:`Runner`.

Request documents for create/update are passed through to the Control Plane,
whose experiment schema is the source of truth.

``client.experiments`` is the :class:`Experiments` instance; calling
``client.experiments(id)`` returns an :class:`ExperimentHandle` with
``.run()``, ``.start()``, ``.end(...)``, and ``.cancel()``.
"""

from __future__ import annotations

from introspection_sdk._async.resources.experiments import (
    AsyncExperimentHandle,
    AsyncExperiments,
)
from introspection_sdk._sync.resources.experiments import (
    ExperimentHandle,
    Experiments,
)

__all__ = [
    "AsyncExperimentHandle",
    "AsyncExperiments",
    "ExperimentHandle",
    "Experiments",
]
