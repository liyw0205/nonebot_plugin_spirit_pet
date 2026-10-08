from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..domain.battle_content import Skill, SkillEffect

if TYPE_CHECKING:
    from .combat import Fighter


BOND_GUARD_AFFINITY = 100


@dataclass
class TimedEffect:
    value: float
    remaining: int
    applied_turn: int


@dataclass
class EffectState:
    weaken: TimedEffect | None = None
    empower: TimedEffect | None = None
    ward: TimedEffect | None = None
    taunt: TimedEffect | None = None
    stunned: bool = False
    control_immunity: int = 0


def attack(unit: Fighter) -> int:
    weakened = unit.effects.weaken.value if unit.effects.weaken else 0
    empowered = unit.effects.empower.value if unit.effects.empower else 0
    return max(1, int(unit.stats.attack * (1 - weakened) * (1 + empowered)))


def absorb_ward(unit: Fighter, amount: int) -> int:
    ward = unit.effects.ward
    if ward is None:
        return 0
    absorbed = min(amount, int(ward.value))
    ward.value -= absorbed
    if ward.value == 0:
        unit.effects.ward = None
    return absorbed


def skip_action(unit: Fighter) -> bool:
    if not unit.effects.stunned:
        return False
    unit.effects.stunned = False
    unit.effects.control_immunity = max(unit.effects.control_immunity, 2)
    return True


def finish_action(unit: Fighter) -> None:
    # The skipped action counts too; newly cast self buffs start ticking on the next action.
    for key in ("weaken", "empower", "ward", "taunt"):
        current = getattr(unit.effects, key)
        if current is not None and current.applied_turn < unit.turns:
            current.remaining -= 1
            if current.remaining == 0:
                setattr(unit.effects, key, None)
    unit.effects.control_immunity = max(0, unit.effects.control_immunity - 1)


def _value(effect: SkillEffect, target: Fighter, multiplier: float) -> float:
    return max(1, int(target.stats.hp * effect.power * multiplier)) if effect.kind == "ward" else effect.power


def useful(effect: SkillEffect, target: Fighter, multiplier: float = 1) -> bool:
    if target.hp <= 0:
        return False
    state = target.effects
    if effect.kind == "stun":
        return not state.stunned and state.control_immunity == 0
    if effect.kind == "cleanse":
        return bool(target.poison_turns or state.weaken or state.stunned)
    if effect.kind == "dispel":
        return bool(target.shield or state.ward or state.empower or state.taunt)
    if effect.kind == "taunt":
        return state.taunt is None or state.taunt.remaining < effect.duration
    current = getattr(state, effect.kind)
    return current is None or current.value < _value(effect, target, multiplier) or current.remaining < effect.duration


def enemy_target(skill: Skill | None, targets: list[Fighter], multiplier: float, rng) -> Fighter:
    candidates = [target for target in targets if target.effects.taunt is not None]
    if not candidates:
        candidates = targets
    if skill and skill.kind == "utility" and any(effect.target == "enemy" for effect in skill.effects):
        applicable = [target for target in targets if any(useful(effect, target, multiplier) for effect in skill.effects)]
        candidates = [target for target in candidates if target in applicable] or candidates
    return candidates[rng.randint(0, len(candidates) - 1)]


def plan(unit: Fighter, skill: Skill, enemy: Fighter, allies: list[Fighter]) -> tuple[tuple[SkillEffect, Fighter], ...]:
    multiplier = unit.skill_multipliers.get(skill.id, 1)
    planned = []
    for effect in skill.effects:
        candidates = {"self": [unit], "enemy": [enemy], "ally": allies}[effect.target]
        candidates = [target for target in candidates if useful(effect, target, multiplier)]
        if not candidates:
            continue
        if effect.kind == "cleanse":
            target = max(candidates, key=lambda target: (
                int(target.effects.stunned) * 3 + bool(target.poison_turns) + bool(target.effects.weaken),
                target.stats.hp - target.hp,
            ))
        elif effect.kind == "empower":
            target = max(candidates, key=lambda target: target.stats.attack)
        else:
            target = candidates[0]
        planned.append((effect, target))
    return tuple(planned)


def apply(unit: Fighter, skill: Skill, planned: tuple[tuple[SkillEffect, Fighter], ...]) -> tuple[str, ...]:
    if unit.hp <= 0:
        return ()
    events = []
    multiplier = unit.skill_multipliers.get(skill.id, 1)
    for effect, target in planned:
        if not useful(effect, target, multiplier):
            continue
        state = target.effects
        if effect.kind == "stun":
            if target.affinity == BOND_GUARD_AFFINITY and not target.bond_protection_used:
                target.bond_protection_used = True
                events.append(f"{target.name}与主人心意相通，抵挡了一次控制。")
                continue
            state.stunned = True
            events.append(f"{target.name}受控，下一次行动跳过。")
        elif effect.kind == "cleanse":
            if state.stunned:
                state.control_immunity = max(state.control_immunity, 1)
            target.poison_damage = target.poison_turns = 0
            state.weaken = None
            state.stunned = False
            events.append(f"{target.name}的毒、虚弱与控制已净化。")
        elif effect.kind == "dispel":
            target.shield = 0
            state.ward = state.empower = state.taunt = None
            events.append(f"{target.name}的护盾、攻击增益与护阵已驱散。")
        elif effect.kind == "taunt":
            current = state.taunt
            duration = max(effect.duration, current.remaining if current else 0)
            state.taunt = TimedEffect(0, duration, target.turns)
            events.append(f"{target.name}摆出护阵，敌方将在 {duration} 次行动内优先攻击该灵宠。")
        else:
            current = getattr(state, effect.kind)
            value = max(_value(effect, target, multiplier), current.value if current else 0)
            duration = max(effect.duration, current.remaining if current else 0)
            setattr(state, effect.kind, TimedEffect(value, duration, target.turns))
            detail = f"临时护盾 {int(value)}" if effect.kind == "ward" else (
                f"攻击{'降低' if effect.kind == 'weaken' else '提高'} {value:.0%}"
            )
            events.append(f"{target.name}获得{detail}，持续 {duration} 次后续行动。")
    return tuple(events)
