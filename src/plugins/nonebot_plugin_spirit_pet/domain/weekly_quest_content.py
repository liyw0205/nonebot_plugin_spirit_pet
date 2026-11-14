from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name, Reward

WeeklyMetric = Literal[
    "weekly_pve_wins", "weekly_pvp_wins", "weekly_expedition_claims",
    "weekly_adventures", "weekly_stage_clears", "weekly_achievement_claims",
    "weekly_cuisine_orders", "weekly_cuisine_practice", "weekly_banquets",
]


class WeeklyQuest(Definition):
    """One weekly goal.

    Progress is counted inside the current Beijing week from records that are
    already permanent (battles, arena results, expeditions, discoveries, chapter
    clears, achievement claims, cuisine orders/practice and banquets), so no
    counter column is needed; the claim row lives in ``quest_progress``.
    """

    id: Identifier
    name: Name
    description: str
    metric: WeeklyMetric
    target: Annotated[int, Field(gt=0, le=1_000_000)]
    reward: Reward
