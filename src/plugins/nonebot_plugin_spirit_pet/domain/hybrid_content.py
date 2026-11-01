from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class Hybrid(Definition):
    """Two different seeds and some stones, fused into one new seed."""

    id: Identifier
    name: Name
    description: str
    seeds: Annotated[list[Identifier], Field(min_length=2, max_length=2)]
    stones: Annotated[int, Field(ge=1, le=100_000)]
    output: Identifier

    @model_validator(mode="after")
    def _sane(self):
        if self.seeds[0] == self.seeds[1]:
            raise ValueError(f"hybrid {self.id} needs two different seeds")
        if self.output in self.seeds:
            raise ValueError(f"hybrid {self.id} must produce a new seed")
        return self
