from typing import Literal

from pydantic import model_validator

from .content import Definition, Identifier, Name, NonNegative, Reward

StandingPerk = Literal["bid_slot", "listing_slot", "tax_rebate"]


class MerchantStanding(Definition):
    """A merchant-standing rung reached by lifetime real trades.

    The progress source is derived (counts of rows in the permanent
    ``market_sales`` / ``market_bid_sales`` ledgers where this player is the
    seller), never stored — so rejects, cancels, expiry and message replays can
    never double-count a trade. Reaching a rung grants its permanent operating
    perk; the one-time reward is claimed through 掌柜领奖.
    """

    id: Identifier
    name: Name
    min_trades: NonNegative
    reward: Reward
    perk: StandingPerk | None = None
    perk_text: str

    @model_validator(mode="after")
    def require_reward_and_text(self):
        if self.reward.stones.maximum == 0 and not self.reward.items:
            raise ValueError(f"merchant standing {self.id} needs a milestone reward")
        if not self.perk_text.strip():
            raise ValueError(f"merchant standing {self.id} needs perk text")
        return self

    @property
    def rebate(self) -> int:
        """Tax-rebate percent this rung alone grants."""
        return 1 if self.perk == "tax_rebate" else 0
