from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class ArenaMeritOffer(Definition):
    """A repeatable reward purchased with wins from the current arena season."""

    id: Identifier
    name: Name
    description: str
    cost: Positive = Field(le=100)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("arena merit reward must not be empty")
        return self
