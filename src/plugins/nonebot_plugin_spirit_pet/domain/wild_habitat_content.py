from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name


class WildHabitatReward(Definition):
    stones: Annotated[int, Field(ge=0, le=10_000)] = 0
    items: dict[Identifier, Annotated[int, Field(gt=0, le=99)]] = Field(default_factory=dict)


class WildHabitatTier(Definition):
    id: Identifier
    name: Name
    contribution_pairs: Annotated[int, Field(ge=1, le=1_000_000)]
    reward: WildHabitatReward


class WildHabitatEvent(Definition):
    id: Identifier
    name: Name
    description: Annotated[str, Field(min_length=1, max_length=120)]
    route: Identifier
    goal_pairs: Annotated[int, Field(ge=1, le=1_000_000)]
    tiers: list[WildHabitatTier] = Field(min_length=1, max_length=5)
