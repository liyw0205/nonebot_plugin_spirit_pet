from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name, Reward


class Expedition(Definition):
    id: Identifier
    name: Name
    description: str
    min_realm: Identifier
    energy: Annotated[int, Field(ge=1, le=100)]
    reward: Reward
