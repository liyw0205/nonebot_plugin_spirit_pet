from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name, Reward

BountyMetric = Literal["hybrid_brews", "alchemy_brews", "contracts_met", "hard_clears"]


class Bounty(Definition):
    """One of the rotating daily bounties.

    Three are offered each Beijing day (a window over the pool derived from the day ordinal, so the
    offer is stable within a day) and every one of them can be claimed independently, unlike the
    single-choice daily assignment.
    """

    id: Identifier
    name: Name
    description: str
    metric: BountyMetric
    target: Annotated[int, Field(gt=0, le=100)]
    reward: Reward
