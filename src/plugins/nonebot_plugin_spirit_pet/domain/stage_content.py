from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name, Positive, Reward


class Stage(Definition):
    """A persistent PVE chapter; unlike a dungeon it has one-time progress."""

    id: Identifier
    name: Name
    description: str
    order: Annotated[int, Field(gt=0, le=1_000_000)]
    min_realm: Identifier
    enemies: list[Identifier] = Field(min_length=1, max_length=5)
    energy: Positive
    reward: Reward
    team: bool = False
    previous_id: Identifier | None = None
