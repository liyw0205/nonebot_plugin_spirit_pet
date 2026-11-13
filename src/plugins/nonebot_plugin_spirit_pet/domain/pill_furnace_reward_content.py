from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class PillFurnaceReward(Definition):
    """One one-time milestone for successfully finishing a furnace recipe."""

    id: Identifier
    product: Identifier
    threshold: int = Field(ge=1, le=99)
    name: Name
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("pill furnace reward must not be empty")
        return self
