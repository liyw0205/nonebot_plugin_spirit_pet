"""Pet race: a scored, non-combat contest built from a pet's final stats.

Each track weights the four stats and boosts one of them through its ``terrain`` entry, so the
same pet can be fast on one track and slow on another. Race time is derived, never simulated:
the weighted stat total becomes speed, and the track length divides it.

Nothing is stored per run except the weekly best and the daily counter, both in
``quest_progress`` (``race_best_<week_start>`` in tenths of a second and
``race_day_<beijing date>`` as the number of runs used today).
"""

from typing import Annotated, Literal

from pydantic import Field

from .content import Definition, Identifier, Name

TerrainStat = Literal["hp", "attack", "defense", "speed"]


class RaceTerrain(Definition):
    stat: TerrainStat
    multiplier: Annotated[float, Field(ge=0.1, le=3)]


class RaceTrack(Definition):
    id: Identifier
    name: Name
    description: str
    length: Annotated[int, Field(ge=100, le=10_000)]
    terrain: RaceTerrain
