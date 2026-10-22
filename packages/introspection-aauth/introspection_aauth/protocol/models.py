"""Values both servers exchange."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from introspection_aauth.protocol.keys import Jwk

#: draft-hardt-aauth-budgets caps an amount at 15 digits.
MAX_BUDGET_AMOUNT = 999_999_999_999_999


class Budget(BaseModel):
    """A budget: `amount / 10**decimals` in `unit` (draft-hardt-aauth-budgets)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    amount: int = Field(ge=0, le=MAX_BUDGET_AMOUNT)
    unit: str = Field(min_length=1, max_length=32)
    decimals: int = Field(ge=0, le=18)

    def same_scale(self, other: Self) -> bool:
        return self.unit == other.unit and self.decimals == other.decimals

    def at_most(self, limit: Self) -> bool:
        """Whether this is no more than `limit`, in the same unit."""
        return self.same_scale(limit) and self.amount <= limit.amount


class Agent(BaseModel):
    """The agent a request came from, once its signature and token verify."""

    model_config = ConfigDict(frozen=True)

    #: `aauth:local@domain`.
    id: str
    #: Its agent provider.
    provider: str
    #: RFC 7638 thumbprint of the key it signs with.
    jkt: str
    jwk: Jwk
    expires_at: int
    #: The Person Server its agent token names, when it names one.
    person_server: str | None = None
    #: The agent token as presented.
    token: str = Field(repr=False)
