from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, NonNegative, Positive


class StageStarReward(Definition):
    """One stage-star milestone reward.

    The reward is static and granted once, when the player's total stage stars
    reach ``stars``. The claim marker lives in ``quest_progress`` and the star
    total is derived from battle records, so no schema change is needed.
    """

    stars: Annotated[int, Field(gt=0, le=10_000)]
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("stage star reward must not be empty")
        return self
