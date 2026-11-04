from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class ShareRankReward(Definition):
    """One one-time reward for reaching a share leaderboard rank."""

    rank: int = Field(ge=1, le=100)
    name: Name
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("share rank reward must not be empty")
        return self
