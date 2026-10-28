from typing import Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class CaveUpgrade(Definition):
    """One paid step from the current level to the next."""

    stones: NonNegative
    items: dict[Identifier, Positive] = {}


class CaveFacility(Definition):
    """A cave facility: a daily action whose strength grows with its level.

    ``yields`` holds one value per level; ``upgrades`` holds exactly one paid step
    between each pair of levels. ``item`` is set only for ``effect == "item"``.
    """

    id: Identifier
    name: Name
    description: str
    effect: Literal["energy", "affinity", "item"]
    yields: list[Positive] = Field(min_length=2, max_length=10)
    item: Identifier | None = None
    upgrades: list[CaveUpgrade] = Field(min_length=1, max_length=9)

    @model_validator(mode="after")
    def _contiguous(self):
        if self.effect == "item" and self.item is None:
            raise ValueError(f"cave facility {self.id} produces an item but names none")
        if self.effect != "item" and self.item is not None:
            raise ValueError(f"cave facility {self.id} names an item but does not produce one")
        if len(self.upgrades) != len(self.yields) - 1:
            raise ValueError(f"cave facility {self.id} needs one upgrade per level step")
        if any(later < earlier for earlier, later in zip(self.yields, self.yields[1:])):
            raise ValueError(f"cave facility {self.id} yields must not decrease")
        return self

    @property
    def max_level(self) -> int:
        return len(self.yields)

    def yield_at(self, level: int) -> int:
        return self.yields[max(0, min(level, self.max_level) - 1)]

    def upgrade_at(self, level: int) -> CaveUpgrade | None:
        return self.upgrades[level - 1] if level < self.max_level else None
