from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive

Stat = Literal["hp", "attack", "defense", "speed"]


class SectRank(Definition):
    rank: Annotated[int, Field(ge=1, le=5)]
    contribution: NonNegative
    rate: Annotated[float, Field(gt=0, le=0.5)]
    stones: NonNegative
    items: dict[Identifier, Positive] = {}


class Sect(Definition):
    """One player sect: a stat passive that grows with contribution ranks."""

    id: Identifier
    name: Name
    description: str
    stat: Stat
    ranks: list[SectRank] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def _ladder(self):
        if [entry.rank for entry in self.ranks] != list(range(1, len(self.ranks) + 1)):
            raise ValueError(f"sect {self.id} ranks must be contiguous from 1")
        if self.ranks[0].contribution != 0:
            raise ValueError(f"sect {self.id} must start at zero contribution")
        if any(
            later.contribution <= earlier.contribution
            for earlier, later in zip(self.ranks, self.ranks[1:])
        ):
            raise ValueError(f"sect {self.id} contribution thresholds must ascend")
        if any(later.rate <= earlier.rate for earlier, later in zip(self.ranks, self.ranks[1:])):
            raise ValueError(f"sect {self.id} passive rates must ascend")
        return self

    @property
    def max_rank(self) -> int:
        return len(self.ranks)

    def rank_at(self, contribution: int) -> SectRank:
        reached = self.ranks[0]
        for entry in self.ranks:
            if contribution >= entry.contribution:
                reached = entry
        return reached
