from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class BattleSupply(Definition):
    """A consumable prepared before a day's battles."""

    id: Identifier
    name: Name
    description: str
    item_id: Identifier
    dealt: Annotated[float, Field(ge=0.75, le=1.25)]
    taken: Annotated[float, Field(ge=0.75, le=1.25)]

    @model_validator(mode="after")
    def check_tradeoff(self):
        if self.dealt == 1 and self.taken == 1:
            raise ValueError(f"battle supply {self.id} must change combat")
        return self
