from pydantic import Field, model_validator

from .content import Definition, Identifier, NonNegative, Positive


class CaveOffering(Definition):
    """One 繁荣 tier's daily offering reward.

    ``tier`` is ``prosperity // per_tier`` clamped to the highest defined tier,
    so the reward grows with total facility levels and never repeats a payout
    the player has not invested for.
    """

    tier: int = Field(ge=1, le=10)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError(f"cave offering tier {self.tier} must pay something")
        return self
