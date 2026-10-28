from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class Restriction(Definition):
    """The lineup rule a forbidden zone imposes on every challenger."""

    type: Literal["solo", "duo", "same_element"]


class ForbiddenDepth(Definition):
    """One sequential depth of a weekly forbidden zone."""

    id: Identifier
    name: Name
    description: str
    order: Annotated[int, Field(gt=0, le=10)]
    min_realm: Identifier
    enemies: list[Identifier] = Field(min_length=1, max_length=5)
    energy: Positive
    reward: Reward


class ForbiddenZone(Definition):
    """A rotating weekly zone: three depths, one restriction, one all-clear bonus."""

    id: Identifier
    name: Name
    description: str
    restriction: Restriction
    bonus: Reward
    depths: list[ForbiddenDepth] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def check_depths(self):
        orders = [depth.order for depth in self.depths]
        if orders != list(range(1, len(self.depths) + 1)):
            raise ValueError("forbidden depths must be ordered contiguously from 1")
        ids = [depth.id for depth in self.depths]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate forbidden depth id")
        names = [depth.name for depth in self.depths]
        if len(set(names)) != len(names):
            raise ValueError("duplicate forbidden depth name")
        return self
