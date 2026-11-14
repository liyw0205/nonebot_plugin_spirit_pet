from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class CuisineMasteryReward(Definition):
    id: Identifier
    dish_id: Identifier
    name: Name
    threshold: Annotated[int, Field(gt=0, le=1_000_000)]
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("cuisine mastery reward must not be empty")
        return self
