from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, NonNegative, Positive

Timestamp = Annotated[int, Field(ge=0)]
Sequence = Annotated[int, Field(gt=0, le=2**63 - 1)]


class FarmContractSeason(Definition):
    number: Literal[1, 2]
    crop_id: Identifier
    cycle: Sequence
    planted_at: Timestamp
    harvested_at: Timestamp


class FarmContractSnapshot(Definition):
    snapshot_version: Literal[1]
    contract_id: Sequence
    plan_id: Identifier
    plan_name: str
    status: Literal["active", "completed", "abandoned"]
    plot: Annotated[int, Field(ge=1, le=6)]
    deposit: Positive
    crops: list[Identifier] = Field(min_length=2, max_length=2)
    delivery: dict[Identifier, Positive]
    reward_stones: NonNegative
    reward_items: dict[Identifier, Positive]
    rule_version: Literal[1]
    signed_at: Timestamp
    updated_at: Timestamp
    seasons: list[FarmContractSeason] = Field(max_length=2)

    @model_validator(mode="after")
    def ordered_seasons_and_terminal_state(self):
        if len(set(self.crops)) != 2 or not self.delivery:
            raise ValueError("farm contract plan must contain two crops and delivery items")
        if self.updated_at < self.signed_at:
            raise ValueError("farm contract time moved before signing")
        if [season.number for season in self.seasons] != list(range(1, len(self.seasons) + 1)):
            raise ValueError("farm contract seasons must be sequential")
        previous = None
        for season in self.seasons:
            if season.crop_id != self.crops[season.number - 1]:
                raise ValueError("farm contract season does not match its frozen crop order")
            if season.planted_at < self.signed_at or season.harvested_at < season.planted_at:
                raise ValueError("farm contract season time is invalid")
            if season.harvested_at > self.updated_at:
                raise ValueError("farm contract harvest is newer than its snapshot")
            if previous is not None and (
                season.cycle <= previous.cycle or season.planted_at < previous.harvested_at
            ):
                raise ValueError("farm contract seasons overlap or reuse a cycle")
            previous = season
        if self.status == "completed" and len(self.seasons) != 2:
            raise ValueError("completed farm contract must contain both seasons")
        return self
