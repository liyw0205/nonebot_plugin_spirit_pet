from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name, Positive, Reward


class TeamTrial(Definition):
    """One weekly team raid: a boss lineup that must fall within a round limit."""

    id: Identifier
    name: Name
    description: str
    min_realm: Identifier
    enemies: list[Identifier] = Field(min_length=1, max_length=5)
    energy: Positive
    round_limit: Annotated[int, Field(ge=3, le=30)]
    reward: Reward
