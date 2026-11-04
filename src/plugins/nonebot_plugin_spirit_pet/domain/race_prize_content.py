from pydantic import Field, model_validator

from .content import Definition, Identifier, NonNegative, Positive


class RacePrize(Definition):
    """One weekly race rank's fixed settlement reward.

    Only the top three ranks are paid. The claim marker lives in
    ``quest_progress`` keyed by the week start, so no schema change is needed.
    """

    rank: int = Field(ge=1, le=3)
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("race prize must not be empty")
        return self
