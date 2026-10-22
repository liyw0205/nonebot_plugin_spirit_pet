"""Gear word definitions: small random stat affixes on equipment.

Each word has a stat and a rolled value range; the rolled value is stored per
stack in `quest_progress` (see `gameplay.gear_words`). A word adds `value %`
of the pet's combat stat as a flat bonus before gear/set bonuses.
"""

from typing import Annotated, Literal

from .content import Definition, Identifier, NonNegative


class GearWord(Definition):
    id: Identifier
    name: str
    stat: Literal["hp", "attack", "defense", "speed"]
    minimum: NonNegative
    maximum: Annotated[int, ...]

    @property
    def low(self) -> int:
        return self.minimum

    @property
    def high(self) -> int:
        return self.maximum