from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class CollectionExchangeOffer(Definition):
    """A repeatable reward purchased with duplicate-species collection stamps."""

    id: Identifier
    name: Name
    description: str
    cost: Positive = Field(le=100)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("collection exchange reward must not be empty")
        return self
