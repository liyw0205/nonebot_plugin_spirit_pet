from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..utils.time import BEIJING_WEEK_EPOCH, WEEK_SECONDS, beijing_week
from .content import Definition, Identifier

LEAGUE_SECONDS = 3 * WEEK_SECONDS


def league_start(timestamp: int) -> int:
    week = beijing_week(timestamp)[0]
    return week - (week - BEIJING_WEEK_EPOCH) % LEAGUE_SECONDS


class SectBossLeaguePrize(Definition):
    rank: Annotated[int, Field(ge=1, le=3)]
    stones: Annotated[int, Field(ge=0, le=2_000)]
    items: dict[Identifier, Annotated[int, Field(ge=1, le=10)]] = Field(max_length=3)

    @model_validator(mode="after")
    def check_amount(self):
        if not 0 < self.stones + sum(self.items.values()) <= 2_000:
            raise ValueError("sect boss league prize must be nonempty and within limits")
        return self


class SectBossLeague(Definition):
    first_season_start: Annotated[int, Field(ge=BEIJING_WEEK_EPOCH)]
    weeks: Literal[3]
    registration_weeks: Literal[1]
    minimum_weeks: Annotated[int, Field(ge=1, le=3)]
    minimum_entrants: Literal[2]
    claim_weeks: Literal[3]
    points_per_week: Literal[10_000]
    tie_break: Literal["points_weeks_best_damage_uid"]
    sect_tie_break: Literal["defeats_progress_id"]
    prizes: list[SectBossLeaguePrize] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_rules(self):
        if league_start(self.first_season_start) != self.first_season_start:
            raise ValueError("sect boss league first season must align to a three-week Beijing rotation")
        if [prize.rank for prize in self.prizes] != [1, 2, 3]:
            raise ValueError("sect boss league prizes must cover ranks 1, 2, 3 in order")
        values = [prize.stones + sum(prize.items.values()) for prize in self.prizes]
        if not values[0] > values[1] > values[2]:
            raise ValueError("sect boss league prizes must decrease by rank")
        return self
