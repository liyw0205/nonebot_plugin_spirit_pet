from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class HerbalismReward(Definition):
    """One one-time milestone for bringing back sites on a herb route."""

    id: Identifier
    route: Identifier
    threshold: Positive = Field(le=9)
    name: Name
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("herbalism reward must not be empty")
        return self
