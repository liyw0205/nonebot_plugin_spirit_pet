from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name
from .wild_capture_content import Rarity


class WildSurveyReward(Definition):
    stones: Annotated[int, Field(ge=0, le=10_000)] = 0
    items: dict[Identifier, Annotated[int, Field(gt=0, le=99)]] = Field(default_factory=dict)


class WildSurveyTier(Definition):
    id: Identifier
    name: Name
    species_count: Annotated[int, Field(ge=1, le=12)]
    required_rarities: list[Rarity] = Field(default_factory=list, max_length=3)
    reward: WildSurveyReward


class WildSurveyRoute(Definition):
    route: Identifier
    title: Name
    description: Annotated[str, Field(min_length=1, max_length=100)]
    tiers: list[WildSurveyTier] = Field(min_length=1, max_length=5)
