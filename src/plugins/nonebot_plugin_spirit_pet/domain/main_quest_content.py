from typing import Annotated

from pydantic import Field

from .achievement_content import AchievementMetric
from .content import Definition, Identifier, Name, Reward


class MainQuest(Definition):
    """One ordered step of the main quest chain.

    Steps reuse the achievement metric vocabulary (progress is derived from the
    player's current save rather than an event counter) but unlock strictly in
    order and pay a one-time reward. Claim state lives in the existing
    ``quest_progress`` table, so no schema change is required.
    """

    id: Identifier
    name: Name
    description: str
    order: Annotated[int, Field(gt=0, le=1_000_000)]
    metric: AchievementMetric
    target: Annotated[int, Field(gt=0, le=1_000_000)]
    reward: Reward
    previous_id: Identifier | None = None
