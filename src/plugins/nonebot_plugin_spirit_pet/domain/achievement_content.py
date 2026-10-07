from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive

AchievementMetric = Literal[
    "species_collected", "pets_owned", "max_realm", "max_layer", "max_bloodline",
    "stage_clears", "pvp_wins", "pve_wins", "lineage_branches",
    "skills_learned", "max_skill_level", "skill_level_sum",
]


class AchievementReward(Definition):
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("achievement reward must not be empty")
        return self


class Achievement(Definition):
    id: Identifier
    name: Name
    description: str
    metric: AchievementMetric
    target: Annotated[int, Field(gt=0, le=1_000_000)]
    reward: AchievementReward
