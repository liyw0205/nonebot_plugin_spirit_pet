from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name, NonNegative, Positive


class Commission(Definition):
    """One merchant order: hand over materials, get paid in stones and reputation."""

    id: Identifier
    name: Name
    description: str
    min_rep: NonNegative
    items: dict[Identifier, Annotated[int, Field(ge=1, le=99)]]
    stones: Positive
    rep: Positive
