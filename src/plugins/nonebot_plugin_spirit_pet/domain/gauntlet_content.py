from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class GauntletRound(Definition):
    enemy: Identifier
    hp_scale: Annotated[float, Field(ge=0.1, le=10)]
    attack_scale: Annotated[float, Field(ge=0.1, le=10)]
    defense_scale: Annotated[float, Field(ge=0.1, le=10)]
    speed_scale: Annotated[float, Field(ge=0.1, le=10)]
    reward: Reward


class Gauntlet(Definition):
    """A weekly attrition run: consecutive fights where the player's hp carries over."""

    id: Identifier
    name: Name
    description: str
    energy: Positive
    bonus: Reward
    rounds: Annotated[list[GauntletRound], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def _sane(self):
        if self.energy > 100:
            raise ValueError(f"gauntlet {self.id} energy exceeds a pet's pool")
        return self
