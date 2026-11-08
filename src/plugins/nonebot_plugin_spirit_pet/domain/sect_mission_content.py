from typing import Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward

# Metrics a sect mission may read. Every one is a monotonic counter written by
# the owning system, so a mission needs no progress row of its own; `period`
# decides whether the day row or the whole current week is read.
SectMissionMetric = Literal[
    "sect_practice", "hard_clears", "contracts_met", "cave_offerings",
    "farm_harvests", "alchemy_brews", "gem_cuts", "banquets_held",
    "hybrid_brews", "encounter_choices",
]


class SectMission(Definition):
    """One sect task: something the player already does, paid in contribution.

    ``period == "day"`` reads today's counter row; ``period == "week"`` sums the
    current Beijing week's day rows. The claim marker and the weekly ledger live
    in ``quest_progress``.
    """

    id: Identifier
    sect: Identifier
    order: int = Field(ge=1, le=10)
    name: Name
    description: str
    metric: SectMissionMetric
    period: Literal["day", "week"] = "day"
    target: Positive
    contribution: Positive
    reward: Reward

    @model_validator(mode="after")
    def require_reward(self):
        if self.reward.stones.maximum == 0 and not self.reward.items:
            raise ValueError(f"sect mission {self.id} must pay something")
        return self
