from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive


class AlchemyRecipe(Definition):
    """A pill recipe: farm produce and materials in, consumables out."""

    id: Identifier
    name: Name
    description: str
    item_id: Identifier
    stones: Positive
    materials: dict[Identifier, Positive] = Field(min_length=1)
    yield_: Annotated[int, Field(ge=1, le=10, alias="yield")]

    @model_validator(mode="after")
    def _sane(self):
        if self.item_id in self.materials:
            raise ValueError(f"alchemy {self.id} cannot consume its own product")
        return self
