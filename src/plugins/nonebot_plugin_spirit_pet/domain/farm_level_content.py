from pydantic import Field, model_validator

from .content import Definition, Identifier, NonNegative, Positive


class FarmLevel(Definition):
    """One rung of the 农事 ladder.

    ``harvests`` is the lifetime harvest count that reaches the level; the
    reward is paid once per player when the level is reached. Level 1 is the
    starting rung and carries no reward. Levels are content, so thresholds and
    payouts stay data-driven instead of hiding in the module.
    """

    level: int = Field(ge=1, le=10)
    harvests: NonNegative
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.level == 1 and (self.stones or self.items):
            raise ValueError("farm level 1 is the starting rung and pays nothing")
        if self.level > 1 and self.stones == 0 and not self.items:
            raise ValueError(f"farm level {self.level} must pay something")
        return self
