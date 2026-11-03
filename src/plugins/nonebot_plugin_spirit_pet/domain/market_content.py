from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive


class Stall(Definition):
    """One market stall tier: listing slots and the tax taken on each sale."""

    id: Identifier
    name: Name
    unlock_cost: NonNegative
    slots: Annotated[int, Field(ge=1, le=12)]
    fee_percent: Annotated[int, Field(ge=0, le=25)]


class MarketRule(Definition):
    """Player market rules: listing lifetime, price band and the stall ladder."""

    listing_days: Annotated[int, Field(ge=1, le=30)]
    min_unit_price: Positive
    max_unit_price: Positive
    max_quantity: Annotated[int, Field(ge=1, le=99)]
    sellable_kinds: list[Literal["material", "consumable"]] = Field(min_length=1, max_length=2)
    stalls: list[Stall] = Field(min_length=1, max_length=6)
    bid_days: Annotated[int, Field(ge=1, le=30)]
    max_bid_quantity: Annotated[int, Field(ge=1, le=99)]
    bid_slots: Annotated[int, Field(ge=1, le=6)]

    @model_validator(mode="after")
    def check_rule(self):
        if self.min_unit_price > self.max_unit_price:
            raise ValueError("market minimum unit price must not exceed the maximum")
        if len(set(self.sellable_kinds)) != len(self.sellable_kinds):
            raise ValueError("market sellable kinds must be unique")
        if self.bid_slots > max(stall.slots for stall in self.stalls):
            raise ValueError("market bid slots must not exceed the largest stall")
        return self
