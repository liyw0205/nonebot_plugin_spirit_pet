from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name

TRADE_SECONDS = 24 * 3600
MAX_TRADE_STONES = 2000
MAX_TRADE_ITEMS = 20


class TradeAsset(Definition):
    item: Identifier | None
    name: Name
    amount: Annotated[int, Field(ge=1, le=MAX_TRADE_STONES)]

    @model_validator(mode="after")
    def bounded_asset(self):
        if self.item is None and self.name != "灵石":
            raise ValueError("trade currency must be stones")
        if self.item is not None and self.amount > MAX_TRADE_ITEMS:
            raise ValueError("trade item amount exceeds the limit")
        return self


class ItemTrade(Definition):
    kind: Literal["item_trade"] = "item_trade"
    version: Literal[1] = 1
    trade_id: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    owner_id: Annotated[str, Field(min_length=1)]
    target_id: Annotated[str, Field(min_length=1)]
    offer: TradeAsset
    request: TradeAsset
    status: Literal["pending", "finished", "rejected", "cancelled", "expired"]
    started_at: Annotated[int, Field(ge=0)]
    expires_at: Annotated[int, Field(ge=0)]
    updated_at: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def consistent_trade(self):
        if self.owner_id == self.target_id or self.offer.item == self.request.item:
            raise ValueError("trade participants and assets must differ")
        if self.expires_at != self.started_at + TRADE_SECONDS or self.updated_at < self.started_at:
            raise ValueError("trade timestamps are not ordered")
        if self.status == "expired":
            if self.updated_at < self.expires_at:
                raise ValueError("trade expired before its deadline")
        elif self.updated_at >= self.expires_at:
            raise ValueError("trade action passed its deadline")
        return self
