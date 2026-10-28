from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive, Reward


class CodexMilestone(Definition):
    """A one-time bonus paid when this many species have been cleared."""

    count: Positive
    items: dict[Identifier, Positive] = {}


class CodexTrial(Definition):
    """One config for the per-species mirror trials (species come from the codex)."""

    id: Identifier
    name: Name
    boost: Annotated[float, Field(ge=1.0, le=5.0)]
    energy: Positive
    reward: Reward
    milestones: list[CodexMilestone] = []

    @model_validator(mode="after")
    def _milestones_ascend(self):
        counts = [milestone.count for milestone in self.milestones]
        if counts != sorted(counts) or len(counts) != len(set(counts)):
            raise ValueError(f"codex trial {self.id} milestones must be unique and ascending")
        return self
