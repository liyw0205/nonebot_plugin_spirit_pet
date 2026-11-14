from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class CuisineOrder(Definition):
    """One weekly delivery order backed by a single-pet cuisine recipe."""

    id: Identifier
    name: Name
    dish_id: Identifier
    portions: Positive = Field(le=12)
    cuisine_level: Positive = Field(le=10)
    required_reputation: NonNegative = Field(le=100)
    reputation: Positive = Field(le=100)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if not self.stones and not self.items:
            raise ValueError("cuisine order reward must not be empty")
        return self
