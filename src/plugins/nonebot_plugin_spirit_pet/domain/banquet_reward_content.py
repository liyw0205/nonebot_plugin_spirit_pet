from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class BanquetReward(Definition):
    """One cumulative reward for successfully held weekly banquets."""

    id: Identifier
    name: Name
    threshold: Positive = Field(le=1000)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("banquet reward must not be empty")
        return self
