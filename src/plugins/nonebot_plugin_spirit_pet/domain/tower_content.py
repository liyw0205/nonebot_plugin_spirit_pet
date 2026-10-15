from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name, Positive, Reward


class TowerFloor(Definition):
    """One single-player floor of the trial tower.

    Floors mirror chapter stages (sequential unlock, one-time first-clear reward)
    but are harder and carry their own command family; progress lives in the
    existing ``pve_stage_progress`` table so no schema change is required.
    """

    id: Identifier
    name: Name
    description: str
    order: Annotated[int, Field(gt=0, le=1_000_000)]
    min_realm: Identifier
    enemies: list[Identifier] = Field(min_length=1, max_length=5)
    energy: Positive
    reward: Reward
    previous_id: Identifier | None = None
