from pydantic import model_validator

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
        return self
