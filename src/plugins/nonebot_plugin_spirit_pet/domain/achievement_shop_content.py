from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class AchievementOfferReward(Definition):
    """The payout of one shop offer; at least one part must be non-empty."""

    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("achievement offer reward must not be empty")
        return self


class AchievementOffer(Definition):
    id: Identifier
    name: Name
    description: str
    cost: Annotated[int, Field(gt=0, le=100_000)]
    reward: AchievementOfferReward
