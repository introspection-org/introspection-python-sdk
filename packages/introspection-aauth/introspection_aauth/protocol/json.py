"""JSON whose shape AAuth leaves open, such as an unverified token's claims,
before it is read into a model."""

from pydantic import JsonValue

JsonObject = dict[str, JsonValue]

__all__ = ["JsonObject", "JsonValue"]
