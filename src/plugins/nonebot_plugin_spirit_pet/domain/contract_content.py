from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name, Positive


class ContractBonus(Definition):
    """Extra payout when a contract's condition held."""

    stones_percent: Annotated[int, Field(ge=0, le=200)] = 0
    exp_percent: Annotated[int, Field(ge=0, le=200)] = 0
    items: dict[Identifier, Positive] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sane(self):
        if self.stones_percent == 0 and self.exp_percent == 0 and not self.items:
            raise ValueError("a contract bonus must pay something")
        return self


class Contract(Definition):
    """A voluntary constraint on an existing dungeon, paid only when it held."""

    id: Identifier
    name: Name
    description: str
    kind: Literal["solo", "speed", "unhurt"]
    rounds: Annotated[int | None, Field(ge=1, le=40)] = None
    bonus: ContractBonus

    @model_validator(mode="after")
    def _sane(self):
        if self.kind == "speed" and self.rounds is None:
            raise ValueError(f"contract {self.id} needs a round limit")
        if self.kind != "speed" and self.rounds is not None:
            raise ValueError(f"contract {self.id} does not use a round limit")
        return self
