from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive, Reward


class SectTrial(Definition):
    """One sect's weekly trial boss.

    The fight runs through the shared PVE path; the reward is paid once per
    Beijing natural week, keyed ``sect_trial_<week start>``.
    """

    id: Identifier
    sect: Identifier
    name: Name
    description: str
    enemy: Identifier
    min_realm: Identifier
    min_rank: int = Field(ge=1, le=5)
    energy: Positive
    contribution: Positive
    reward: Reward

    @model_validator(mode="after")
    def require_reward(self):
        if self.reward.stones.maximum == 0 and not self.reward.items:
            raise ValueError(f"sect trial {self.id} must pay something")
        if self.energy > 100:
            raise ValueError(f"sect trial {self.id} energy exceeds capacity")
        return self
