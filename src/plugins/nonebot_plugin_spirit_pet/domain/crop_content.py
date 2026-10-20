from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive, Range

CropDuration = Annotated[int, Field(ge=60, le=86_400)]


class Crop(Definition):
    """One farm crop: grown from its seed over a real-time duration."""

    id: Identifier
    name: Name
    seed_item: Identifier
    duration: CropDuration
    reward_exp: NonNegative = 0
    reward_stones: NonNegative = 0
    reward_items: dict[Identifier, Range] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_yield(self):
        if self.reward_exp == 0 and self.reward_stones == 0 and not self.reward_items:
            raise ValueError("crop must yield something")
        return self
