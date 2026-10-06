from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name, NonNegative, Positive


class StatMultipliers(Definition):
    hp: Annotated[float, Field(ge=0.5, le=2)] = 1
    attack: Annotated[float, Field(ge=0.5, le=2)] = 1
    defense: Annotated[float, Field(ge=0.5, le=2)] = 1
    speed: Annotated[float, Field(ge=0.5, le=2)] = 1


class LineageCost(Definition):
    exp: NonNegative
    stones: NonNegative
    items: dict[Identifier, Positive] = Field(default_factory=dict)


class Lineage(Definition):
    id: Identifier
    name: Name
    description: str
    species_id: Identifier
    min_bloodline: Annotated[int, Field(ge=1, le=10)]
    cost: LineageCost
    stat_multipliers: StatMultipliers
