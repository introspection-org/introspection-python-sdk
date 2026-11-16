"""``client.routines`` / ``runner.routines`` — DP namespace for
``/v1/routines``.

A routine is scheduled work on a project: a prompt a person set up
(``kind=None``), which creates a task per firing or posts into an
existing one (``task_id``), or platform work (``observation_synthesis``,
``observation_clustering``, ``project_check_in``). Every firing is
recorded as an ``introspection.routines.triggered`` or
``introspection.routines.skipped`` event, readable through
``client.events`` with the ``routine_id`` / ``task_id`` filters.

A prompt routine that starts a task per run can also be started by
events: ``triggers`` lists them beside its ``schedule`` triggers (a
Slack, GitHub or Linear integration's events, or a ``webhook``
connector's calls), and ``trigger(parameters=...)``
runs it by hand with a JSON object, which the SDK uploads through the
Files API and attaches to the run (``parameters=<local JSON path>``
reads one from disk first, and ``parameters=<File or UUID>`` attaches one
already uploaded). Either way the run's parameters (the manual object,
or the event's body) arrive as ``parameters.json`` and the prompt reads
their top-level keys as ``@parameters.<name>``.

The server serves these routes to project administrators only today and
answers anyone else with a 403. introspection-cloud#3137 (not yet
shipped) opens them to members for their own routines that post into
one of their own tasks.

``runner.routines`` sends the runner's token. The platform is being
changed so that a runner a member opens for themself carries
``routines:read`` and ``routines:write``.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.routines import (
    PARAMETERS_FILE_NAME,
    PARAMETERS_FILE_TTL_SECONDS,
    AsyncRoutines,
    ConditionInput,
    FileRefInput,
    RepositoryInput,
    SynthesisInput,
    TriggerInput,
)
from introspection_sdk._sync.runner_resources.routines import (
    Routines,
)

__all__ = [
    "AsyncRoutines",
    "Routines",
    "ConditionInput",
    "FileRefInput",
    "RepositoryInput",
    "SynthesisInput",
    "PARAMETERS_FILE_NAME",
    "PARAMETERS_FILE_TTL_SECONDS",
    "TriggerInput",
]
