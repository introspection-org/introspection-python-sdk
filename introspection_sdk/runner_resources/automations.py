"""``client.automations`` / ``runner.automations`` — DP namespace for
``/v1/automations``.

An automation is scheduled work on a project: a prompt a person set up
(``kind=None``), which creates a task per firing or posts into an
existing one (``task_id``), or platform work (``observation_synthesis``,
``observation_clustering``, ``project_check_in``). Every firing is
recorded as an ``introspection.automation.triggered`` or
``introspection.automation.skipped`` event, readable through
``client.events`` with the ``automation_id`` / ``task_id`` filters.

The server serves these routes to project administrators only today and
answers anyone else with a 403. introspection-cloud#3137 (not yet
shipped) opens them to members for their own automations that post into
one of their own tasks.

``runner.automations`` sends the runner's token. The platform is being
changed so that a runner a member opens for themself carries
``automations:read`` and ``automations:write``.
"""

from __future__ import annotations

from introspection_sdk._async.runner_resources.automations import (
    AsyncAutomations,
)
from introspection_sdk._sync.runner_resources.automations import (
    Automations,
)
from introspection_sdk.runner_resources._automations_common import (
    MetadataInput,
)

__all__ = [
    "AsyncAutomations",
    "Automations",
    "MetadataInput",
]
