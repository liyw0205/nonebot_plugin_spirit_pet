from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name, Reward

WeeklyMetric = Literal[
    "weekly_pve_wins", "weekly_pvp_wins", "weekly_expedition_claims",
    "weekly_adventures", "weekly_stage_clears", "weekly_achievement_claims",
]


class WeeklyQuest(Definition):
    """One weekly goal.

    Progress is counted inside the current Beijing week from records that are
    already permanent (battles, arena results, expeditions, discoveries, chapter
    clears, achievement claims), so no counter column is needed; the claim row
    lives in the existing ``quest_progress`` table.
    """

    id: Identifier
    name: Name
    description: str
    metric: WeeklyMetric
    target: Annotated[int, Field(gt=0, le=1_000_000)]
    reward: Reward
