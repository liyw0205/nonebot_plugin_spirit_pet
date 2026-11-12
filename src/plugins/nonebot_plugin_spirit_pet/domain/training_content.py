from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name

TrainingMove = Literal["probe", "strike", "brace", "charge", "burst"]


class TrainingTrial(Definition):
    id: Identifier
    name: Name
    description: str = Field(min_length=1)
    health: Annotated[float, Field(ge=2, le=4)]
    defense: Annotated[float, Field(ge=0.15, le=0.45)]
    pressure: Annotated[float, Field(ge=0.15, le=0.35)]
    moves: list[TrainingMove] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def rhythm(self):
        if not self.description.strip():
            raise ValueError("training trial needs a description")
        for index, move in enumerate(self.moves):
            if move == "charge" and (index == 4 or self.moves[index + 1] != "burst"):
                raise ValueError("training charge must be followed by burst")
            if move == "burst" and (index == 0 or self.moves[index - 1] != "charge"):
                raise ValueError("training burst needs a preceding charge")
        if not {"strike", "charge", "burst"}.issubset(self.moves):
            raise ValueError("training trial needs strike and a charge/burst pair")
        return self


class TrainingRule(Definition):
    energy: Annotated[int, Field(ge=12, le=20)]
    food: Annotated[int, Field(ge=1, le=2)]
    daily_limit: Annotated[int, Field(ge=1, le=2)]
    proficiency_per_cast: Annotated[int, Field(ge=1, le=2)]
    proficiency_cap: Annotated[int, Field(ge=1, le=8)]
    win_bond: Annotated[int, Field(ge=1, le=4)]
    loss_bond: Annotated[int, Field(ge=0, le=1)]
