"""Version information for introspection-sdk package."""

from importlib.metadata import version

VERSION = version("introspection-sdk")

#: Sent on REST calls and on both OTLP streams, so telemetry and API traffic
#: are attributable to this SDK and this release.
USER_AGENT = f"introspection-sdk/{VERSION}"
