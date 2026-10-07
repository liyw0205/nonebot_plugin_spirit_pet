from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class ArenaTier(Definition):
    id: Identifier
    name: Name
    minimum_rating: NonNegative
    stones: NonNegative
    items: dict[Identifier, Positive]

    @model_validator(mode="after")
    def check_reward(self):
        if not self.stones and not self.items:
            raise ValueError("arena tier reward must not be empty")
        return self


class ArenaRules(Definition):
    initial_rating: NonNegative
    min_realm: Identifier
    max_rating_gap: Annotated[int, Field(ge=1, le=10_000)]
    daily_matches: Annotated[int, Field(ge=1, le=100)]
    pair_daily_matches: Annotated[int, Field(ge=1, le=100)]
    pair_season_matches: Annotated[int, Field(ge=1, le=10_000)]
    reward_matches: Annotated[int, Field(ge=1, le=10_000)]
    reward_opponents: Annotated[int, Field(ge=1, le=1_000)]
    rating_delta: Annotated[int, Field(ge=1, le=10_000)]
    energy: Annotated[int, Field(ge=1, le=100)]
    tiers: list[ArenaTier] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def check_quotas_and_tiers(self):
        if self.pair_daily_matches > self.daily_matches:
            raise ValueError("pair daily matches must not exceed daily matches")
        if self.pair_daily_matches > self.pair_season_matches:
            raise ValueError("pair daily matches must not exceed pair season matches")
        if self.reward_opponents > self.reward_matches:
            raise ValueError("reward opponents must not exceed reward matches")
        if self.reward_matches > self.daily_matches * 28:
            raise ValueError("reward matches exceed shortest season capacity")
        if self.tiers[0].minimum_rating != 0:
            raise ValueError("arena tiers must begin at zero rating")
        if len({tier.id for tier in self.tiers}) != len(self.tiers):
            raise ValueError("duplicate arena tier id")
        if len({tier.name for tier in self.tiers}) != len(self.tiers):
            raise ValueError("duplicate arena tier name")
        for previous, current in zip(self.tiers, self.tiers[1:]):
            if current.minimum_rating <= previous.minimum_rating:
                raise ValueError("arena tier ratings must strictly increase")
            if current.stones < previous.stones or any(
                current.items.get(item_id, 0) < quantity
                for item_id, quantity in previous.items.items()
            ):
                raise ValueError("arena tier rewards must not decrease")
        return self
