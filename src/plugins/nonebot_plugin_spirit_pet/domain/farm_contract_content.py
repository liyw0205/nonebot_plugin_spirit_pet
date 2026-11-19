from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class FarmContractPlan(Definition):
    id: Identifier
    name: Name
    min_farm_level: Annotated[int, Field(ge=1, le=10)]
    deposit: Positive
    crops: list[Identifier] = Field(min_length=2, max_length=2)
    delivery: dict[Identifier, Positive]
    reward_stones: NonNegative
    reward_items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_cycle_and_payout(self):
        if len(set(self.crops)) != 2:
            raise ValueError("farm contract crops must be distinct")
        if not self.delivery:
            raise ValueError("farm contract requires delivery materials")
        if self.reward_stones == 0 and not self.reward_items:
            raise ValueError("farm contract requires a reward")
        return self
