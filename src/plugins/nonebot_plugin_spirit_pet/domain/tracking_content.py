from typing import Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class TrackingMap(Definition):
    """Sites are numbered 1..16, row first on a four by four grid."""

    id: Identifier
    name: Name
    description: str
    sites: list[Name] = Field(min_length=16, max_length=16)
    terrains: list[Literal[0, 1]] = Field(min_length=16, max_length=16)
    terrain_names: list[Name] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def balanced_grid(self):
        if len(set(self.sites)) != 16 or len(set(self.terrain_names)) != 2:
            raise ValueError("tracking map needs unique sites and terrain names")
        if self.terrains.count(0) != 8 or self.terrains.count(1) != 8:
            raise ValueError("tracking map needs eight sites of each terrain")
        return self
