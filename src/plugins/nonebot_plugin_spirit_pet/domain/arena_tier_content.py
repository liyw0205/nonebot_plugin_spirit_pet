from pydantic import Field, model_validator

from .content import Definition, Identifier, NonNegative, Positive


class ArenaTierReward(Definition):
    """One arena tier's in-season achievement reward.

    The reward is static and granted once per season, when the player's current
    season rating reaches that tier. The claim marker lives in ``quest_progress``
    keyed by season, so no schema change is needed.
    """

    tier: Identifier
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("arena tier reward must not be empty")
        return self
