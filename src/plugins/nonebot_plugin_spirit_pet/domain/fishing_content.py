from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class FishingCatch(Definition):
    """One weighted entry in a spot's catch table."""

    item: Identifier
    weight: Positive
    minimum: Positive
    maximum: Positive

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError(f"fishing catch {self.item} amount range is inverted")
        return self


class FishingSpot(Definition):
    """A realm-gated water spot with its own weighted catch table.

    A cast costs the active pet's energy and is limited by a daily counter; the
    per-player 鱼获 record lives in ``quest_progress`` as one row per caught item.
    """

    id: Identifier
    name: Name
    description: str
    realm: NonNegative
    energy: Positive
    catches: list[FishingCatch]

    @model_validator(mode="after")
    def usable_table(self):
        if not self.description.strip():
            raise ValueError(f"fishing spot {self.id} needs a description")
        if len(self.catches) < 3:
            raise ValueError(f"fishing spot {self.id} needs at least three catches")
        items = [entry.item for entry in self.catches]
        if len(set(items)) != len(items):
            raise ValueError(f"fishing spot {self.id} repeats a catch item")
        if self.energy > 100:
            raise ValueError(f"fishing spot {self.id} energy exceeds 100")
        return self


class FishingBait(Definition):
    id: Identifier
    name: Name
    description: str
    cost_item: Identifier
    cost_quantity: Annotated[int, Field(ge=1, le=10)]
    favored_items: list[Identifier]
    multiplier: Annotated[int, Field(ge=2, le=5)]

    @model_validator(mode="after")
    def usable_bait(self):
        if not self.description.strip():
            raise ValueError(f"fishing bait {self.id} needs a description")
        if not self.favored_items or len(set(self.favored_items)) != len(self.favored_items):
            raise ValueError(f"fishing bait {self.id} needs distinct favored items")
        if self.id == "plain" or self.name == "素饵":
            raise ValueError("plain fishing bait is reserved")
        return self
