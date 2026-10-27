from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name


class AscensionStage(Definition):
    """One segment of the ascension trial; the enemy pool is real content."""

    id: Identifier
    name: Name
    description: str
    order: Annotated[int, Field(ge=1, le=10)]
    enemy: Identifier
