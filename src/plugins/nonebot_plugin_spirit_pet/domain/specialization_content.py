"""Skill specialisation: one pet commits to one learned skill for an archetype bonus.

An archetype is derived from the skill itself, so the only content is the four rate entries:

* any hostile effect (stun/weaken/dispel/taunt) → ``control``
* a heal skill or any beneficial effect → ``support``
* ``all`` targeting → ``multi``
* everything else → ``single``

``Catalog._validate_specializations`` refuses a catalogue where some skill classifies to an
archetype that has no entry, so no skill can ever be unspecialisable.
"""

from typing import Annotated

from pydantic import Field

from .content import Definition, Identifier, Name

HOSTILE_EFFECTS = frozenset({"stun", "weaken", "dispel", "taunt"})


def skill_archetype(skill) -> str:
    """Classify a skill into exactly one specialisation archetype."""
    kinds = {effect.kind for effect in skill.effects}
    if kinds & HOSTILE_EFFECTS:
        return "control"
    if skill.kind == "heal" or kinds:
        return "support"
    if skill.targeting == "all":
        return "multi"
    return "single"


class Specialization(Definition):
    id: Identifier
    name: Name
    description: str
    rate: Annotated[float, Field(ge=0.05, le=0.3)]
