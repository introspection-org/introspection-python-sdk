"""DP-facing :class:`Runner` returned by ``runtimes(...).run()`` and
``experiments(...).run()``.

The Runner is an agent-session with a runtime context attached. It
owns the DP endpoint + session-locator JWT minted by the CP
``/run`` call and exposes ``runner.tasks``, ``runner.files``,
``runner.automations``, ``runner.connections`` and
the read-only ``runner.conversations`` namespaces that target that
endpoint. The
DP-side agent-session machinery materializes the real access token
from the session lookup on each request, so the SDK does not need to
drive refresh itself —
``runner.refresh()`` stays as a manual escape hatch that re-calls
CP ``/run``. ``runner.close()`` flips a local ``_closed`` flag
and tears down the underlying HTTP client; server-side revoke is
a follow-up.
"""

from __future__ import annotations

from introspection_sdk._async.runner import (
    AsyncRunner,
)
from introspection_sdk._sync.runner import (
    Runner,
)

__all__ = ["AsyncRunner", "Runner"]
