from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Reward


class FamilyTrialStage(Definition):
    enemy: Identifier
    max_rounds: Annotated[int, Field(ge=1, le=40)]
    hp_scale: Annotated[float, Field(ge=0.1, le=10)] = 1
    attack_scale: Annotated[float, Field(ge=0.1, le=10)] = 1
    defense_scale: Annotated[float, Field(ge=0.1, le=10)] = 1
    speed_scale: Annotated[float, Field(ge=0.1, le=10)] = 1
    reward: Reward


class FamilyTrial(Definition):
    id: Identifier
    name: Name
    description: Annotated[str, Field(min_length=1, max_length=120)]
    energy: Annotated[int, Field(ge=1, le=100)]
    weekly_runs: Literal[1] = 1
    minimum_members: Annotated[int, Field(ge=2, le=3)] = 2
    maximum_members: Annotated[int, Field(ge=2, le=3)] = 3
    bonus: Reward
    stages: list[FamilyTrialStage] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def check_member_bounds(self):
        if self.minimum_members > self.maximum_members:
            raise ValueError("family trial member bounds are inverted")
        return self


class FamilyTrialCatalog(Definition):
    rotation: list[Identifier] = Field(min_length=2, max_length=12)
    trials: list[FamilyTrial] = Field(min_length=2, max_length=12)

    @model_validator(mode="after")
    def check_ids(self):
        trial_ids = [trial.id for trial in self.trials]
        if len(trial_ids) != len(set(trial_ids)):
            raise ValueError("family trial ids must be unique")
        if len({trial.name for trial in self.trials}) != len(self.trials):
            raise ValueError("family trial names must be unique")
        if len(self.rotation) != len(set(self.rotation)):
            raise ValueError("family trial rotation must not repeat ids")
        if set(self.rotation) != set(trial_ids):
            raise ValueError("family trial rotation must cover all trials")
        return self
