from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name


ResonanceRate = Annotated[float, Field(ge=0, le=0.08)]


class ResonanceBonuses(Definition):
    hp: ResonanceRate = 0
    attack: ResonanceRate = 0
    defense: ResonanceRate = 0
    speed: ResonanceRate = 0

    @model_validator(mode="after")
    def check_total(self):
        values = self.model_dump().values()
        if not any(values) or sum(values) > 0.1:
            raise ValueError("resonance bonuses must be positive and total at most 10%")
        return self


class Resonance(Definition):
    id: Identifier
    name: Name
    description: str
    required_species: list[Identifier] = Field(min_length=2, max_length=2)
    bonuses: ResonanceBonuses

    @model_validator(mode="after")
    def check_species(self):
        if len(set(self.required_species)) != len(self.required_species):
            raise ValueError("resonance requires two different species")
        return self
