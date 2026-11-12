"""Lossless local combat state for resumable games, separate from report summaries."""

from dataclasses import asdict

from ..domain.battle_content import Skill, Talent
from ..domain.content import Stats
from .combat import Fighter
from .effects import EffectState, TimedEffect


def pack(unit: Fighter) -> dict:
    data = asdict(unit)
    data["stats"] = unit.stats.model_dump(mode="json")
    data["skills"] = [skill.model_dump(mode="json") for skill in unit.skills]
    data["talent"] = unit.talent.model_dump(mode="json") if unit.talent else None
    return data


def unpack(value: dict) -> Fighter:
    data = dict(value)
    data["stats"] = Stats.model_validate(data["stats"])
    data["skills"] = tuple(Skill.model_validate(skill) for skill in data["skills"])
    data["talent"] = Talent.model_validate(data["talent"]) if data["talent"] else None
    data["elements"] = tuple(data["elements"])
    data["equipment_sets"] = tuple(data["equipment_sets"])
    state = dict(data["effects"])
    for key in ("weaken", "empower", "ward", "taunt"):
        state[key] = TimedEffect(**state[key]) if state[key] else None
    data["effects"] = EffectState(**state)
    return Fighter(**data)
