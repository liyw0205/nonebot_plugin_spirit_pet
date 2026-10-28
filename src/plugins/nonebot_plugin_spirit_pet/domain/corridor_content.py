from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class Linear(Definition):
    """A per-floor reward line: ``base + growth * (floor - 1)``."""

    base: NonNegative
    growth: NonNegative


class Milestone(Definition):
    floor: Annotated[int, Field(ge=1, le=60)]
    items: dict[Identifier, Positive] = {}


class Scaling(Definition):
    """Compounding per-floor growth, applied as ``(1 + rate) ** (floor - 1)``."""

    hp: Annotated[float, Field(ge=0, le=1)] = 0
    attack: Annotated[float, Field(ge=0, le=1)] = 0
    defense: Annotated[float, Field(ge=0, le=1)] = 0
    speed: Annotated[float, Field(ge=0, le=1)] = 0


class Corridor(Definition):
    id: Identifier
    name: Name
    description: str
    energy: Positive
    max_floor: Annotated[int, Field(ge=5, le=60)]
    base_enemy: Identifier
    scaling: Scaling
    stones_per_floor: Linear
    exp_per_floor: Linear
    milestones: list[Milestone] = []

    @model_validator(mode="after")
    def _check(self):
        if self.energy > 100:
            raise ValueError(f"corridor {self.id} energy exceeds a pet's pool")
        floors = [milestone.floor for milestone in self.milestones]
        if floors != sorted(floors) or len(floors) != len(set(floors)):
            raise ValueError(f"corridor {self.id} milestones must be unique and ascending")
        if floors and floors[-1] > self.max_floor:
            raise ValueError(f"corridor {self.id} milestone beyond the last floor")
        if not any(rate for rate in self.scaling.model_dump().values()):
            raise ValueError(f"corridor {self.id} does not scale any stat")
        return self

    def stones_at(self, floor: int) -> int:
        return self.stones_per_floor.base + self.stones_per_floor.growth * (floor - 1)

    def exp_at(self, floor: int) -> int:
        return self.exp_per_floor.base + self.exp_per_floor.growth * (floor - 1)
