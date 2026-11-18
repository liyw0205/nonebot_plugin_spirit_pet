from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class RuinHall(Definition):
    name: Name
    description: str
    treasure: Identifier
    risk: Annotated[int, Field(ge=1, le=3)]


class RuinSite(Definition):
    id: Identifier
    name: Name
    description: str
    min_realm: Identifier
    halls: Annotated[list[RuinHall], Field(min_length=3, max_length=3)]
    reward: Reward
    rich_reward: Reward
    bond: Annotated[int, Field(strict=True, ge=1, le=100)]
    energy: Positive = 12
    food: Positive = 1

    @model_validator(mode="after")
    def validate_halls(self):
        if len({hall.name for hall in self.halls}) != len(self.halls):
            raise ValueError("ruin hall names must be unique")
        if len({hall.treasure for hall in self.halls}) < 2:
            raise ValueError("ruin halls need at least two treasures")
        if self.reward == self.rich_reward:
            raise ValueError("rich ruin reward must differ from base reward")
        return self
