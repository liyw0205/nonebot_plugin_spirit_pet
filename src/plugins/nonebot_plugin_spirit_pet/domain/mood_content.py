"""Pet mood: a short-term per-pet state that decays with neglect and scales combat stats.

Mood is *derived*, never stored per day: ``quest_progress`` keeps one ``last_care_<pet_id>`` row
holding the Beijing day the pet was last cared for, and the value is recomputed from the elapsed
days on every read, so nothing has to run on a schedule and a missed day cannot corrupt anything.

The four levels live in ``data/moods.json``; their ``rate`` values must equal
``rules.mood.rates`` for the same id, which ``Catalog._validate_moods`` enforces so the two files
cannot drift apart.
"""

from typing import Annotated

from pydantic import Field, model_validator

from .content import Definition, Identifier, Name

LAST_CARE_PREFIX = "last_care_"


def mood_of(levels, value: int):
    """Return the level whose threshold is the highest one not above ``value``."""
    ordered = sorted(levels, key=lambda level: level.threshold)
    chosen = ordered[0]
    for level in ordered:
        if value >= level.threshold:
            chosen = level
    return chosen


class MoodLevel(Definition):
    id: Identifier
    name: Name
    description: str
    threshold: Annotated[int, Field(ge=0, le=10)]
    rate: Annotated[float, Field(ge=-0.3, le=0.3)]

    @model_validator(mode="after")
    def _sane(self):
        if self.threshold == 0 and self.rate > 0:
            raise ValueError(f"mood {self.id} at threshold 0 must not be a bonus")
        return self
