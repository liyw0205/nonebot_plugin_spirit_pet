from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class Difficulty(Definition):
    """A voluntary difficulty tier: stronger enemies for a larger payout."""

    id: Identifier
    name: Name
    description: str
    enemy_scale: Annotated[float, Field(ge=1.0, le=3.0)]
    reward_percent: Annotated[int, Field(ge=0, le=200)]

    @model_validator(mode="after")
    def _sane(self):
        if self.enemy_scale == 1.0 and self.reward_percent > 0:
            raise ValueError(f"difficulty {self.id} pays extra without raising enemy stats")
        if self.enemy_scale > 1.0 and self.reward_percent == 0:
            raise ValueError(f"difficulty {self.id} raises enemy stats without paying extra")
        return self
