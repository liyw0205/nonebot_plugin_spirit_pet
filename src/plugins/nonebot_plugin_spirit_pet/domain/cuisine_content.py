from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Effects, Identifier, Name, NonNegative, Positive


class CuisineDish(Definition):
    """One spirit-kitchen recipe.

    A single-pet meal references a consumable `item` it produces; a banquet carries
    `effects` that are served to the whole roster at once. Exactly one of the two is set.
    """

    id: Identifier
    name: Name
    description: str
    level: Annotated[int, Field(ge=1, le=10)]
    heat: Annotated[int, Field(ge=1, le=5)]
    stones: NonNegative
    ingredients: dict[Identifier, Positive] = Field(min_length=1, max_length=4)
    item: Identifier | None = None
    effects: Effects | None = None

    @model_validator(mode="after")
    def check_output(self):
        if (self.item is None) == (self.effects is None):
            raise ValueError("a dish needs exactly one of item or effects")
        if self.effects is not None:
            effects = self.effects
            if effects.breakthrough_bonus:
                raise ValueError("banquet effects cannot include a breakthrough bonus")
            if not (effects.energy or effects.exp or effects.affinity):
                raise ValueError("banquet effects must recover something")
        return self
