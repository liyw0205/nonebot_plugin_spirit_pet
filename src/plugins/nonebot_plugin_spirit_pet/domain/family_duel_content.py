from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Reward


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
