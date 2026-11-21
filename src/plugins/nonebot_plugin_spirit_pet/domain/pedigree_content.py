from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name


class PedigreeReward(Definition):
    stones: Annotated[int, Field(ge=0, le=10_000)] = 0
    items: dict[Identifier, Annotated[int, Field(gt=0, le=99)]] = Field(default_factory=dict)


class PedigreeMilestone(Definition):
    id: Identifier
    name: Name
    minimum_generation: Annotated[int, Field(ge=1, le=100)]
    minimum_members: Annotated[int, Field(ge=3, le=10_000)]
    reward: PedigreeReward
