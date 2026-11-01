from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class EscortNpc(Definition):
    """The unit that must survive; it fights on the player's side but is not a pet."""

    name: Name
    hp: Positive
    attack: Annotated[int, Field(ge=0, le=100_000)]
    defense: Annotated[int, Field(ge=0, le=100_000)]
    speed: Positive


class EscortRewards(Definition):
    full: Reward
    partial: Reward

    @model_validator(mode="after")
    def _graded(self):
        if self.full.stones.minimum < self.partial.stones.minimum:
            raise ValueError("the full escort payout must not be smaller than the partial one")
        if self.full.exp.minimum < self.partial.exp.minimum:
            raise ValueError("the full escort payout must not pay less exp than the partial one")
        return self


class EscortMission(Definition):
    id: Identifier
    name: Name
    description: str
    energy: Positive
    npc: EscortNpc
    waves: Annotated[list[Annotated[list[Identifier], Field(min_length=1, max_length=3)]], Field(min_length=1, max_length=5)]
    rewards: EscortRewards

    @model_validator(mode="after")
    def _sane(self):
        if self.energy > 100:
            raise ValueError(f"escort {self.id} energy exceeds a pet's pool")
        return self
