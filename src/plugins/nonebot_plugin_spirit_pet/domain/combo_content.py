from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class ComboBonuses(Definition):
    hp: Annotated[float, Field(ge=0, le=0.1)] = 0.0
    attack: Annotated[float, Field(ge=0, le=0.1)] = 0.0
    defense: Annotated[float, Field(ge=0, le=0.1)] = 0.0
    speed: Annotated[float, Field(ge=0, le=0.1)] = 0.0

    @model_validator(mode="after")
    def _bounds(self):
        if not any((self.hp, self.attack, self.defense, self.speed)):
            raise ValueError("combo bonuses must not all be zero")
        if self.hp + self.attack + self.defense + self.speed > 0.15:
            raise ValueError("combo bonuses must total at most 15%")
        return self


class Combo(Definition):
    """Two skills equipped on the same pet grant a small stat bonus."""

    id: Identifier
    name: Name
    description: str
    skills: Annotated[list[Identifier], Field(min_length=2, max_length=2)]
    bonuses: ComboBonuses

    @model_validator(mode="after")
    def _distinct(self):
        if self.skills[0] == self.skills[1]:
            raise ValueError(f"combo {self.id} needs two different skills")
        return self
