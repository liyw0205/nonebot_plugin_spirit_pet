from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class TrackingReward(Definition):
    """A one-time reward for distinct successfully excavated sites on one map."""

    id: Identifier
    map_id: Identifier
    threshold: int = Field(ge=1, le=16)
    name: Name
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("tracking reward must not be empty")
        return self
