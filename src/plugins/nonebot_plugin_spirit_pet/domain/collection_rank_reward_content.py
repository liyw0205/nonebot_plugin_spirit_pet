from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class CollectionRankReward(Definition):
    """One one-time collection leaderboard milestone.

    ``rank`` is the highest rank that unlocks the reward. Claim markers live in
    ``quest_progress`` keyed by this threshold, so the reward is once per player.
    """

    rank: int = Field(ge=1, le=10)
    name: Name
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("collection rank reward must not be empty")
        return self
