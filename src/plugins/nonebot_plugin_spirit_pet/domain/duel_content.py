from typing import Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Reward, Stats


class DuelOpponent(Definition):
    """A sparring guardian fought one exchange at a time."""

    id: Identifier
    name: Name
    description: str
    realm: Identifier
    stats: Stats
    reward: Reward
    intents: list[Literal["assault", "guard", "feint"]] = Field(
        default_factory=lambda: ["assault", "guard", "feint"], min_length=2, max_length=6,
    )

    @model_validator(mode="after")
    def _sane(self):
        if len(set(self.intents)) < 2:
            raise ValueError("duel intents must offer at least two different moves")
        if self.reward.stones.maximum <= 0 and self.reward.exp.maximum <= 0:
            raise ValueError(f"duel opponent {self.id} must grant stones or exp")
        return self
