from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, NonNegative, Positive, Reward


class ContractStage(Definition):
    """One delivery inside a merchant contract: fixed goods for fixed stones."""

    items: dict[Identifier, Positive] = Field(min_length=1, max_length=4)
    stones: NonNegative = 0


class MerchantContract(Definition):
    """A multi-stage trade commitment with a deadline and a deposit at risk.

    The deposit is charged on accept and returned only on completion; abandoning
    or letting the deadline pass forfeits it. Stages must be delivered in order,
    which is what makes holding stock across days a real decision.
    """

    id: Identifier
    name: Name
    description: str
    min_rep: NonNegative
    days: int = Field(ge=1, le=14)
    deposit: NonNegative
    rep: NonNegative
    stages: list[ContractStage] = Field(min_length=2, max_length=4)
    bonus: Reward

    @model_validator(mode="after")
    def require_payoff(self):
        if self.bonus.stones.maximum == 0 and not self.bonus.items:
            raise ValueError(f"merchant contract {self.id} needs a completion bonus")
        if all(stage.stones == 0 for stage in self.stages) and not self.bonus.items:
            raise ValueError(f"merchant contract {self.id} pays nothing")
        return self

    @property
    def payout(self) -> int:
        """Stones the contract can pay in total, deposit excluded."""
        return sum(stage.stones for stage in self.stages) + self.bonus.stones.maximum
