from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class VisitReward(Definition):
    """One permanent reward unlocked by completed friend visits."""

    id: Identifier
    name: Name
    threshold: Positive = Field(le=1_000_000)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("visit reward must not be empty")
        return self
