from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Stats


class DrillDummy(Definition):
    """A wooden dummy: a fixed-stat sparring target that grants nothing.

    Stats are anchored to the same realm's dungeon enemies so the drill measures the
    lineup against content the player will actually face, never against a made-up band.
    """

    id: Identifier
    name: Name
    description: str
    realm: Identifier
    stats: Stats
    elements: list[Identifier] = Field(min_length=1, max_length=4)
    primary_element: Identifier
    order: Annotated[int, Field(ge=1, le=99)]

    @model_validator(mode="after")
    def _sane(self):
        if self.primary_element not in self.elements:
            raise ValueError(f"drill dummy {self.id} primary element must be one of its elements")
        return self
