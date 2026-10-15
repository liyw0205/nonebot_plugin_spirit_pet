from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name, Reward

JourneyKind = Literal[
    "clear_dungeon", "win_at", "discover", "collect_species", "enable_resonance", "reach_realm",
]


class JourneyTask(Definition):
    """What one chapter asks for; every kind is derived from existing state."""

    kind: JourneyKind
    target: Identifier
    count: Annotated[int, Field(gt=0, le=1_000_000)] = 1


class Journey(Definition):
    """One chapter of the 山海行纪 story chain.

    Chapters unlock strictly in order (``previous_id``) and pay a one-time
    reward. Progress is derived from permanent records -- dungeon wins,
    discovered encounters, owned species, the active resonance and the best
    realm -- so no schema change is needed; claim state lives in the existing
    ``quest_progress`` table.
    """

    id: Identifier
    name: Name
    realm: Identifier
    story: str
    task: JourneyTask
    reward: Reward
    previous_id: Identifier | None = None
