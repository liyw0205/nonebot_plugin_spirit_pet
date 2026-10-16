from pydantic import Field, model_validator

from .content import Definition, Identifier, NonNegative, Positive


class CodexReward(Definition):
    """One species' one-time collection reward.

    The reward is static and granted once, when the player has collected that
    species. The claim marker lives in ``quest_progress`` and collection stays
    derived from the ``pets`` table, so no schema change is needed.
    """

    species: Identifier
    stones: NonNegative = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_reward(self):
        if self.stones == 0 and not self.items:
            raise ValueError("codex reward must not be empty")
        return self
