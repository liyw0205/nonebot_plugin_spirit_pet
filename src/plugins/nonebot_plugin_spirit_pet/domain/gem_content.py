from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name


class SocketGem(Definition):
    """A gem that can be set into one gear slot and scales a single base stat."""

    id: Identifier
    name: Name
    item_id: Identifier
    stat: Literal["hp", "attack", "defense", "speed"]
    rate: Annotated[float, Field(ge=0.01, le=0.25)]
