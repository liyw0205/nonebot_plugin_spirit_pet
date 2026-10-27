from typing import Annotated, Literal

from pydantic import Field

from .achievement_content import AchievementMetric
from .content import Definition, Identifier, Name

TitleMetric = AchievementMetric | Literal[
    "main_quest_claims", "weekly_claims", "battle_pass_premium_claims",
    "ascended_pets", "rebirth_count",
]


class Title(Definition):
    """One displayable title.

    Titles are derived: a title is held while the player's current save satisfies
    its metric, so nothing is stored and the highest ordered held title is shown
    automatically. ``order`` doubles as the priority.
    """

    id: Identifier
    name: Name
    description: str
    metric: TitleMetric
    target: Annotated[int, Field(gt=0, le=1_000_000)]
    order: Annotated[int, Field(gt=0, le=1_000_000)]
