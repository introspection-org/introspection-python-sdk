"""Internal logging and platform utilities."""

import logging
import os
import platform

logger = logging.getLogger("introspection-sdk")

# Configure logger if not already configured
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    )
    logger.addHandler(handler)
    # Set log level from environment variable or root logger
    log_level_str = os.getenv("INTROSPECTION_LOG_LEVEL", "").upper()
    if log_level_str and hasattr(logging, log_level_str):
        logger.setLevel(getattr(logging, log_level_str))
    else:
        root_logger = logging.getLogger()
        logger.setLevel(
            root_logger.getEffectiveLevel()
            if root_logger.level != logging.NOTSET
            else logging.INFO
        )


def platform_is_emscripten() -> bool:
    """Return True if the platform is Emscripten, e.g. Pyodide.

    Threads cannot be created on Emscripten, so we need to avoid any code
    that creates threads.

    Returns:
        ``True`` when running on Emscripten (e.g. Pyodide in a browser).
    """
    return platform.system().lower() == "emscripten"
