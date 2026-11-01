from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


class Formation(Definition):
    """A lineup slot: multipliers on base stats, always a trade-off."""

    id: Identifier
    name: Name
    description: str
    rates: dict[Annotated[str, Field(pattern="^(hp|attack|defense|speed)$")], Annotated[float, Field(ge=0.5, le=1.8)]]

    @model_validator(mode="after")
    def _trade_off(self):
        missing = {"hp", "attack", "defense", "speed"} - set(self.rates)
        if missing:
            raise ValueError(f"formation {self.id} is missing rates for {sorted(missing)}")
        if not any(rate > 1 for rate in self.rates.values()):
            raise ValueError(f"formation {self.id} must raise at least one stat")
        if not any(rate < 1 for rate in self.rates.values()):
            raise ValueError(f"formation {self.id} must cost at least one stat")
        return self


class Formations(Definition):
    positions: Annotated[list[Formation], Field(min_length=1)]

    @property
    def by_id(self) -> dict[str, Formation]:
        return {position.id: position for position in self.positions}
