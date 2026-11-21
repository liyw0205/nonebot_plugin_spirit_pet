from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..utils.time import BEIJING_WEEK_EPOCH, WEEK_SECONDS, beijing_week
from .content import Definition, Identifier, Name, Reward

LEAGUE_SECONDS = 3 * WEEK_SECONDS


def league_start(timestamp: int) -> int:
    week = beijing_week(timestamp)[0]
    return week - (week - BEIJING_WEEK_EPOCH) % LEAGUE_SECONDS


class FamilyDuelRating(Definition):
    id: Identifier
    name: Name
    max_rounds: Annotated[int, Field(ge=1, le=40)]
    require_both_alive: bool
    require_both_skills: Literal[True] = True
    reward: Reward


class FamilyDuel(Definition):
    id: Identifier
    name: Name
    description: Annotated[str, Field(min_length=1, max_length=120)]
    min_realm: Identifier
    enemies: list[Identifier] = Field(min_length=1, max_length=3)
    energy: Annotated[int, Field(ge=1, le=100)]
    max_rounds: Annotated[int, Field(ge=3, le=40)]
    ratings: list[FamilyDuelRating] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def check_ratings(self):
        first, second = self.ratings
        if len(self.enemies) != len(set(self.enemies)):
            raise ValueError("family duel enemies must be unique")
        if first.id == second.id or first.name == second.name:
            raise ValueError("family duel ratings must have unique ids and names")
        if first.max_rounds != self.max_rounds or second.max_rounds >= first.max_rounds:
            raise ValueError("family duel ratings must provide a stricter second round threshold")
        if first.require_both_alive or not second.require_both_alive:
            raise ValueError("family duel ratings must progress from any survivors to both alive")
        for low, high in ((first.reward.exp, second.reward.exp), (first.reward.stones, second.reward.stones)):
            if high.minimum < low.minimum or high.maximum < low.maximum:
                raise ValueError("stricter family duel rating rewards must not decrease")
        item_ids = set(first.reward.items) | set(second.reward.items)
        for item_id in item_ids:
            low = first.reward.items.get(item_id)
            high = second.reward.items.get(item_id)
            if low is not None and (high is None or high.minimum < low.minimum or high.maximum < low.maximum):
                raise ValueError("stricter family duel rating rewards must not decrease")
        return self


class FamilyDuelCatalog(Definition):
    rotation: list[Identifier] = Field(min_length=3, max_length=3)
    duels: list[FamilyDuel] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_rotation(self):
        ids = [duel.id for duel in self.duels]
        if len(ids) != len(set(ids)) or len({duel.name for duel in self.duels}) != len(ids):
            raise ValueError("family duels must have unique ids and names")
        if len(set(self.rotation)) != len(self.rotation) or set(self.rotation) != set(ids):
            raise ValueError("family duel rotation must cover every duel exactly once")
        return self


class LeagueRating(Definition):
    id: Identifier
    name: Name
    points: Annotated[int, Field(ge=0, le=100)]


class LeaguePrize(Definition):
    rank: Annotated[int, Field(ge=1, le=3)]
    stones: Annotated[int, Field(ge=0, le=2_000)]
    items: dict[Identifier, Annotated[int, Field(ge=1, le=10)]] = Field(max_length=3)

    @model_validator(mode="after")
    def check_amount(self):
        if not 0 < self.stones + sum(self.items.values()) <= 2_000:
            raise ValueError("family duel league prize must be nonempty and within limits")
        return self


class FamilyDuelLeague(Definition):
    first_season_start: Annotated[int, Field(ge=316800)]
    weeks: Literal[3]
    registration_weeks: Literal[1]
    minimum_matches: Annotated[int, Field(ge=1, le=3)]
    minimum_finishers: Literal[2]
    claim_weeks: Literal[3]
    tie_break: Literal["points_high_ratings_wins_matches_uid"]
    ratings: list[LeagueRating] = Field(min_length=2, max_length=2)
    prizes: list[LeaguePrize] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_rules(self):
        low, high = self.ratings
        if low.id == high.id or low.name == high.name or low.points >= high.points:
            raise ValueError("family duel league rating ids must be unique and points increasing")
        if [prize.rank for prize in self.prizes] != [1, 2, 3]:
            raise ValueError("family duel league prizes must cover ranks 1, 2, 3 in order")
        if self.first_season_start % WEEK_SECONDS != BEIJING_WEEK_EPOCH % WEEK_SECONDS or (
            self.first_season_start - BEIJING_WEEK_EPOCH
        ) % LEAGUE_SECONDS:
            raise ValueError("family duel league first season must align to a three-week Beijing rotation")
        return self
