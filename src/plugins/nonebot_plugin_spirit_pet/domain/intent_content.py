from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class BattleIntent(Definition):
    """A stance that scales outgoing and incoming damage instead of the four base stats."""

    id: Identifier
    name: Name
    description: str
    dealt: Annotated[float, Field(ge=0.5, le=1.5)]
    taken: Annotated[float, Field(ge=0.5, le=1.5)]

    @model_validator(mode="after")
    def check_trade_off(self):
        # A stance must both give and take, so the two multipliers move the same way: both up (hit
        # harder, get hit harder) or both down (hit softer, get hit softer). Every other combination
        # is either free power or a pure penalty, and neither is a decision.
        if (self.dealt - 1) * (self.taken - 1) <= 0:
            raise ValueError(f"{self.id} must raise both damage multipliers or lower both")
        return self
