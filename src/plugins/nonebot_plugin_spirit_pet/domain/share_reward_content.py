from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class ShareReward(Definition):
    """One one-time milestone for distinct readers of a player's shares."""

    readers: int = Field(ge=1, le=100)
    name: Name
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("share reward must not be empty")
        return self
