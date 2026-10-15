from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name, Reward

DailyAssignmentMetric = Literal[
    "daily_pve", "daily_pvp", "daily_discovery", "daily_expedition", "daily_claim", "daily_training",
]


class DailyAssignment(Definition):
    """One of the rotating daily assignments.

    Three are offered each Beijing day (derived from the day ordinal, so the
    choice is stable within a day) and the player may claim exactly one. Every
    metric is scoped to today and derived from timestamped records, so no
    schema change is needed; the pick is recorded in ``quest_progress``.
    """

    id: Identifier
    name: Name
    description: str
    metric: DailyAssignmentMetric
    target: Annotated[int, Field(gt=0, le=1_000_000)]
    reward: Reward
