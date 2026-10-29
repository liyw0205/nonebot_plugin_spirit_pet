from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class SurvivalMilestone(Definition):
    rounds: Positive
    reward: Reward


class SurvivalTrial(Definition):
    """An unkillable guardian: score is how many rounds your lineup survives."""

    id: Identifier
    name: Name
    description: str
    enemy: Identifier
    hp_multiplier: Annotated[float, Field(gt=0, le=100)]
    attack_multiplier: Annotated[float, Field(gt=0, le=100)]
    defense_multiplier: Annotated[float, Field(ge=0, le=100)]
    speed_multiplier: Annotated[float, Field(gt=0, le=100)]
    energy: Positive
    milestones: list[SurvivalMilestone] = Field(min_length=1)

    @model_validator(mode="after")
    def _ladder(self):
        rounds = [milestone.rounds for milestone in self.milestones]
        if rounds != sorted(rounds) or len(rounds) != len(set(rounds)):
            raise ValueError(f"survival trial {self.id} milestones must be unique and ascending")
        return self

    @property
    def target(self) -> int:
        return self.milestones[-1].rounds
