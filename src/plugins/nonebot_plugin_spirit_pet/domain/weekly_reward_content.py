from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class WeeklyReward(Definition):
    id: Identifier
    name: Name
    threshold: Positive = Field(le=12)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if not self.stones and not self.items:
            raise ValueError("weekly reward must not be empty")
        return self
