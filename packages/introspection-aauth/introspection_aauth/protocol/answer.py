"""What a protocol request is answered with, for any web framework."""

from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass(frozen=True)
class Answer:
    """What a protocol request is answered with, for any web framework: its
    status, its body, serialised with members that are None left out, and
    its headers."""

    status: int
    body: BaseModel
    headers: dict[str, str] = field(default_factory=dict)

    def content(self) -> bytes:
        return self.body.model_dump_json(exclude_none=True).encode()
