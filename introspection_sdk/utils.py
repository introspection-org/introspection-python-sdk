"""Internal logging and platform utilities."""

import logging
import os
import platform

logger = logging.getLogger("introspection-sdk")

# A library configures no output of its own. Attaching a StreamHandler and
# forcing INFO at import meant merely calling ``init()`` printed the SDK's
# own log lines to the application's stderr, and duplicated them into
# whatever handlers the application had already set up. ``NullHandler``
# keeps the "no handlers could be found" warning away and leaves the
# decision where it belongs.
logger.addHandler(logging.NullHandler())

# ``INTROSPECTION_LOG_LEVEL`` remains an opt-in for the SDK's own logger; if
# it is unset the level is inherited from the application's configuration.
_log_level_str = os.getenv("INTROSPECTION_LOG_LEVEL", "").upper()
if _log_level_str and hasattr(logging, _log_level_str):
    logger.setLevel(getattr(logging, _log_level_str))


def platform_is_emscripten() -> bool:
    """Return True if the platform is Emscripten, e.g. Pyodide.

    Threads cannot be created on Emscripten, so we need to avoid any code
    that creates threads.

    Returns:
        ``True`` when running on Emscripten (e.g. Pyodide in a browser).
    """
    return platform.system().lower() == "emscripten"
