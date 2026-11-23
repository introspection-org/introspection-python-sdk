"""GenAI spans → an ATIF trajectory, and an ATIF trajectory → run messages."""

from introspection_atif.genai_span import GenAiSpan, GenAiSpanList
from introspection_atif.messages import AtifConversionError, atif_to_messages
from introspection_atif.projection import AtifProjection, spans_to_atif
from introspection_atif.trajectory import ATIF_SCHEMA_VERSION, AtifTrajectory

__all__ = [
    "ATIF_SCHEMA_VERSION",
    "AtifConversionError",
    "AtifProjection",
    "AtifTrajectory",
    "GenAiSpan",
    "GenAiSpanList",
    "atif_to_messages",
    "spans_to_atif",
]
