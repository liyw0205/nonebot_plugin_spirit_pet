from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class TribulationModifier(Definition):
    """One numeric risk knob applied to a dungeon's enemies."""

    id: Identifier
    name: Name
    description: str
    hp: Annotated[float, Field(ge=0.1, le=100)]
    attack: Annotated[float, Field(ge=0.1, le=100)]
    defense: Annotated[float, Field(ge=0.1, le=100)]
    speed: Annotated[float, Field(ge=0.1, le=100)]
    round_limit: Annotated[int, Field(ge=0, le=30)] = 0
    energy_multiplier: Annotated[float, Field(ge=0.5, le=3)] = 1.0
    reward: Reward

    @model_validator(mode="after")
    def _limit(self):
        if 0 < self.round_limit < 3:
            raise ValueError(f"modifier {self.id} round limit must be 0 or at least 3")
        return self


class Tribulation(Definition):
    id: Identifier
    name: Name
    description: str
    energy: Positive
    slots: Annotated[int, Field(ge=1, le=5)]
    bonus: Reward
    modifiers: list[TribulationModifier] = Field(min_length=3)

    @model_validator(mode="after")
    def _unique(self):
        ids = [modifier.id for modifier in self.modifiers]
        if len(ids) != len(set(ids)):
            raise ValueError(f"tribulation {self.id} has duplicate modifiers")
        return self
