from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name


class SectOffer(Definition):
    """One exchange offer: contribution points for an existing item, weekly limited."""

    id: Identifier
    name: Name
    description: str
    item_id: Identifier
    cost: Annotated[int, Field(ge=1, le=100_000)]
    weekly_limit: Annotated[int, Field(ge=1, le=10)]
