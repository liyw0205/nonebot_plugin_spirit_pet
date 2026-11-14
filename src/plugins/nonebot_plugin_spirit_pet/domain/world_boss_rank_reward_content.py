from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class WorldBossRankReward(Definition):
    """One-time weekly reward for a world-boss contribution rank."""

    rank: int = Field(ge=1, le=10)
    name: Name
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("world boss rank reward must not be empty")
        return self
