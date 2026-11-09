from typing import Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive

PlayStat = Literal["attack", "defense", "speed"]


class PlayGameMilestone(Definition):
    """One mastery tier of a play game, paid once when claimed."""

    at: Positive
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def needs_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("play game milestone needs a reward")
        return self


class PlayGame(Definition):
    """A daily 嬉戏 mini-game resolved against one pet attribute.

    Mastery is a plain ``quest_progress`` counter per game, so the ladder keeps
    counting across days while the daily play quota resets each Beijing day.
    """

    id: Identifier
    name: Name
    description: str
    stat: PlayStat
    great_bonus: NonNegative = 0
    great_items: dict[Identifier, Positive] = Field(default_factory=dict)
    milestones: list[PlayGameMilestone]

    @model_validator(mode="after")
    def ordered(self):
        if not self.description.strip():
            raise ValueError(f"play game {self.id} needs a description")
        if not self.milestones:
            raise ValueError(f"play game {self.id} needs at least one milestone")
        thresholds = [milestone.at for milestone in self.milestones]
        if thresholds != sorted(set(thresholds)):
            raise ValueError(f"play game {self.id} milestones must strictly increase")
        return self
