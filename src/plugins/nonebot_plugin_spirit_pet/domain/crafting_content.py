from collections.abc import Mapping
from typing import Annotated

from pydantic import Field

from .battle_content import ForgeLevel
from .content import Definition, Identifier, Name, Positive


class Recipe(Definition):
    id: Identifier
    name: Name
    item_id: Identifier
    stones: Positive
    materials: dict[Identifier, Positive] = Field(min_length=1)
    salvage_materials: dict[Identifier, Positive] = Field(min_length=1)
    enhancement_refund_percent: Annotated[int, Field(ge=0, le=50)]


def salvage_yield(recipe: Recipe, forge_levels: Mapping[int, ForgeLevel], enhancement: int) -> dict[str, int]:
    if type(enhancement) is not int or enhancement not in forge_levels:
        raise ValueError("unsupported equipment enhancement")
    invested: dict[str, int] = {}
    for level in range(enhancement):
        for key, amount in forge_levels[level].upgrade_items.items():
            invested[key] = invested.get(key, 0) + amount
    result = dict(recipe.salvage_materials)
    for key, amount in invested.items():
        refund = amount * recipe.enhancement_refund_percent // 100
        if refund:
            result[key] = result.get(key, 0) + refund
    return result
