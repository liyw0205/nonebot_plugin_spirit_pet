from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name


class PairPractice(Definition):
    id: Identifier
    name: Name
    description: str = Field(min_length=1)
    enemies: list[Identifier] = Field(min_length=2, max_length=2)
    progress: Annotated[int, Field(ge=1, le=2)]
