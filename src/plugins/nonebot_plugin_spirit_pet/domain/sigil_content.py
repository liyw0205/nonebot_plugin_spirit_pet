from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name

SigilRequirement = Literal["achievements", "collection", "bond", "realm"]


class SigilBonus(Definition):
    hp: Annotated[int, Field(ge=0, le=60)] = 0
    attack: Annotated[int, Field(ge=0, le=60)] = 0
    defense: Annotated[int, Field(ge=0, le=60)] = 0
    speed: Annotated[int, Field(ge=0, le=60)] = 0

    @model_validator(mode="after")
    def _non_empty(self):
        if not any((self.hp, self.attack, self.defense, self.speed)):
            raise ValueError("sigil bonuses must not all be zero")
        return self


class SigilRequirementRule(Definition):
    kind: SigilRequirement
    value: Annotated[int, Field(ge=1, le=100_000)]


class Sigil(Definition):
    """A permanent, unlocked-by-progress emblem that grants flat stats while slotted."""

    id: Identifier
    name: Name
    description: str
    bonuses: SigilBonus
    requires: SigilRequirementRule
